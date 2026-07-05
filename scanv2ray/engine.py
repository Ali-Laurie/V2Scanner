from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED


def run_pipeline(scanner, links, *, method, timeout, precheck_workers, test_workers,
                 should_stop, wait_if_paused,
                 report_precheck, report_dead, report_test):
    """
    Streaming precheck -> (validate+realtest) pipeline with a bounded rolling test pool.
    Peak concurrent xray == test_workers (each test worker holds at most one long-running
    xray at a time). Real testing begins as soon as the first config passes precheck.

    See module contract for callback semantics. Returns a small stats dict.
    """
    total = len(links)
    pre_done = 0
    reachable = 0
    test_done = 0

    stats = {
        'total': total,
        'pre_done': 0,
        'reachable': 0,
        'test_done': 0,
        'stopped': False,
    }

    if total == 0:
        report_precheck(0, 0, 0)
        return stats

    pre_pool = ThreadPoolExecutor(max_workers=max(1, precheck_workers))
    test_pool = ThreadPoolExecutor(max_workers=max(1, test_workers))

    pending_pre = set()
    pre_link = {}       # future -> original link (survives wait() reassigning pending_pre)
    pending_test = {}   # future -> item
    stopped = False

    def _finish_test(fut):
        nonlocal test_done
        item = pending_test.pop(fut)
        parsed = item.get('parsed')
        link = item.get('link', '')
        try:
            result = fut.result()
        except Exception:
            result = None
        test_done += 1
        if result is None:
            report_dead(link, parsed, 'connectivity_or_speed_failed', 'test')
        report_test(item, result, test_done, reachable)

    def _finish_precheck(fut):
        nonlocal pre_done, reachable
        link = pre_link.pop(fut, '')
        try:
            item = fut.result()
        except Exception:
            item = None
        pre_done += 1
        if item and item.get('ok'):
            reachable += 1
            tf = test_pool.submit(scanner.validate_and_test, item, timeout, method)
            pending_test[tf] = item
        elif item is not None:
            report_dead(item.get('link', link), item.get('parsed'),
                        item.get('reason', 'precheck_failed'), 'precheck')
        else:
            # precheck_link raised (e.g. bad port/host type) -> keep the link accounted for
            report_dead(link, None, 'precheck_exception', 'precheck')
        report_precheck(pre_done, total, reachable)

    try:
        for link in links:
            fut = pre_pool.submit(scanner.precheck_link, link)
            pending_pre.add(fut)
            pre_link[fut] = link

        while pending_pre or pending_test:
            wait_if_paused()
            if should_stop():
                stopped = True
                scanner.request_abort()
                for f in pending_pre:
                    f.cancel()
                break

            if pending_pre:
                # Block briefly on prechecks while draining tests non-blocking.
                done_pre, pending_pre = wait(pending_pre, timeout=0.2,
                                             return_when=FIRST_COMPLETED)
                for fut in done_pre:
                    _finish_precheck(fut)

                if pending_test:
                    done_test, _ = wait(set(pending_test.keys()), timeout=0,
                                        return_when=FIRST_COMPLETED)
                    for fut in done_test:
                        _finish_test(fut)
            elif pending_test:
                done_test, _ = wait(set(pending_test.keys()), timeout=0.2,
                                    return_when=FIRST_COMPLETED)
                for fut in done_test:
                    _finish_test(fut)
    finally:
        pre_pool.shutdown(wait=False, cancel_futures=True)
        test_pool.shutdown(wait=False, cancel_futures=True)

    stats['pre_done'] = pre_done
    stats['reachable'] = reachable
    stats['test_done'] = test_done
    stats['stopped'] = stopped
    return stats
