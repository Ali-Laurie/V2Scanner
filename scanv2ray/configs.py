def _parse_alpn(value):
    if not value:
        return ['h2', 'http/1.1']
    if isinstance(value, str):
        return [item.strip() for item in value.split(',') if item.strip()]
    return list(value)


def build_xray_stream_settings(parsed):
    transport_type = parsed.get('transport_type', 'tcp') or 'tcp'
    security_mode = parsed.get('security_mode', 'none') or 'none'
    host = parsed.get('host', '')
    sni = parsed.get('sni', '')
    host_header = parsed.get('host_header', '')
    extra = parsed.get('extra', {}) or {}

    stream_settings = {
        'network': transport_type,
        'security': security_mode
    }

    if security_mode in ('tls', 'xtls'):
        tls_target = sni or host_header or host or ''
        if security_mode == 'xtls':
            stream_settings['xtlsSettings'] = {
                'serverName': tls_target,
                'alpn': _parse_alpn(extra.get('alpn', ''))
            }
        else:
            stream_settings['tlsSettings'] = {
                'serverName': tls_target,
                'alpn': _parse_alpn(extra.get('alpn', ''))
            }
    elif security_mode == 'reality':
        reality_target = sni or host_header or host or ''
        reality_settings = {
            'serverName': reality_target,
            'fingerprint': extra.get('fp', 'chrome') or 'chrome',
            'publicKey': extra.get('pbk', ''),
            'shortId': extra.get('sid', ''),
            'spiderX': extra.get('spx', '') or '/'
        }
        if extra.get('alpn'):
            reality_settings['alpn'] = _parse_alpn(extra.get('alpn', ''))
        stream_settings['realitySettings'] = reality_settings

    if transport_type == 'ws':
        stream_settings['wsSettings'] = {
            'path': parsed.get('path') or '/',
            'headers': {
                'Host': host_header or sni or host or ''
            }
        }
    elif transport_type == 'grpc':
        stream_settings['grpcSettings'] = {
            'serviceName': parsed.get('path') or extra.get('serviceName', '')
        }
    elif transport_type == 'h2':
        stream_settings['httpSettings'] = {
            'path': parsed.get('path') or '/',
            'host': [host_header or sni or host or '']
        }
    elif transport_type == 'quic':
        stream_settings['quicSettings'] = {
            'security': extra.get('security', 'none'),
            'key': extra.get('key', ''),
            'header': {
                'type': extra.get('headerType', 'none')
            }
        }
    elif transport_type == 'kcp':
        stream_settings['kcpSettings'] = {
            'mtu': 1350,
            'tti': 20,
            'uplinkCapacity': 5,
            'downlinkCapacity': 20,
            'congestion': False,
            'readBufferSize': 1,
            'writeBufferSize': 1,
            'header': {
                'type': extra.get('headerType', 'none')
            }
        }

    return stream_settings


def make_xray_config(parsed, local_port):
    if not parsed:
        return None
    if parsed.get('proto') in ('hysteria', 'hysteria2'):
        return None

    outbound = {
        'protocol': parsed['proto'],
        'settings': {},
        'streamSettings': build_xray_stream_settings(parsed)
    }

    if parsed['proto'] == 'vmess':
        outbound['settings'] = {
            'vnext': [
                {
                    'address': parsed['host'],
                    'port': parsed['port'],
                    'users': [
                        {
                            'id': parsed['credentials'],
                            'alterId': 0,
                            'security': 'auto'
                        }
                    ]
                }
            ]
        }
    elif parsed['proto'] == 'vless':
        user_obj = {
            'id': parsed['credentials'],
            'encryption': 'none'
        }
        if parsed.get('flow'):
            user_obj['flow'] = parsed['flow']
        outbound['settings'] = {
            'vnext': [
                {
                    'address': parsed['host'],
                    'port': parsed['port'],
                    'users': [user_obj]
                }
            ]
        }
    elif parsed['proto'] == 'trojan':
        outbound['settings'] = {
            'servers': [
                {
                    'address': parsed['host'],
                    'port': parsed['port'],
                    'password': parsed['credentials']
                }
            ]
        }
    elif parsed['proto'] == 'ss':
        outbound['protocol'] = 'shadowsocks'
        method, password = parsed['credentials'].split(':', 1) if ':' in parsed['credentials'] else ('aes-256-gcm', parsed['credentials'])
        outbound['settings'] = {
            'servers': [
                {
                    'address': parsed['host'],
                    'port': parsed['port'],
                    'method': method,
                    'password': password
                }
            ]
        }
    elif parsed['proto'] == 'socks':
        server_obj = {
            'address': parsed['host'],
            'port': parsed['port']
        }
        creds = parsed.get('credentials') or ''
        if ':' in creds:
            user, password = creds.split(':', 1)
            server_obj['users'] = [{'user': user, 'pass': password}]
        outbound['settings'] = {
            'servers': [server_obj]
        }
    elif parsed['proto'] == 'http':
        server_obj = {
            'address': parsed['host'],
            'port': parsed['port']
        }
        creds = parsed.get('credentials') or ''
        if ':' in creds:
            user, password = creds.split(':', 1)
            server_obj['users'] = [{'user': user, 'pass': password}]
        outbound['settings'] = {
            'servers': [server_obj]
        }
    elif parsed['proto'] in ('hysteria', 'hysteria2'):
        extra = parsed.get('extra', {}) or {}
        server_obj = {
            'address': parsed['host'],
            'port': parsed['port'],
            'password': parsed['credentials'],
            'protocol': extra.get('protocol', 'udp') or 'udp'
        }
        if extra.get('auth'):
            server_obj['auth'] = extra['auth']
        if extra.get('obfs'):
            server_obj['obfs'] = extra['obfs']
        if extra.get('up'):
            try:
                server_obj['up_mbps'] = float(extra['up'])
            except Exception:
                pass
        if extra.get('down'):
            try:
                server_obj['down_mbps'] = float(extra['down'])
            except Exception:
                pass
        if extra.get('peer'):
            server_obj['peer'] = extra['peer']
        outbound = {
            'protocol': 'hysteria',
            'settings': {
                'servers': [server_obj]
            },
            'streamSettings': build_xray_stream_settings(parsed)
        }

    config = {
        'log': {'loglevel': 'none'},
        'inbounds': [
            {
                'port': local_port,
                'listen': '127.0.0.1',
                'protocol': 'http'
            }
        ],
        'outbounds': [outbound]
    }
    return config


def build_singbox_transport(parsed):
    transport_type = parsed.get('transport_type', 'tcp') or 'tcp'
    host = parsed.get('host', '')
    sni = parsed.get('sni', '')
    host_header = parsed.get('host_header', '')
    path = parsed.get('path') or '/'
    extra = parsed.get('extra', {}) or {}

    if transport_type == 'ws':
        return {
            'type': 'ws',
            'path': path,
            'headers': {
                'Host': host_header or sni or host or ''
            }
        }
    elif transport_type == 'grpc':
        return {
            'type': 'grpc',
            'service_name': parsed.get('path') or extra.get('serviceName', '')
        }
    elif transport_type == 'h2':
        return {
            'type': 'http',
            'path': path,
            'headers': {
                'Host': host_header or sni or host or ''
            }
        }
    elif transport_type == 'quic':
        return {
            'type': 'quic',
            'security': extra.get('security', 'none'),
            'key': extra.get('key', ''),
            'header': {
                'type': extra.get('headerType', 'none')
            }
        }
    elif transport_type == 'kcp':
        return {
            'type': 'kcp',
            'header': {
                'type': extra.get('headerType', 'none')
            }
        }
    return None


def make_singbox_config(parsed, local_port):
    if not parsed:
        return None

    outbound = {
        'tag': 'proxy',
        'server': parsed['host'],
        'server_port': parsed['port']
    }

    if parsed['proto'] == 'ss':
        outbound['type'] = 'shadowsocks'
        method, password = parsed['credentials'].split(':', 1) if ':' in parsed['credentials'] else ('aes-256-gcm', parsed['credentials'])
        outbound['method'] = method
        outbound['password'] = password
    elif parsed['proto'] == 'vmess':
        outbound['type'] = 'vmess'
        outbound['uuid'] = parsed['credentials']
        outbound['alter_id'] = 0
        outbound['security'] = 'auto'
    elif parsed['proto'] == 'vless':
        outbound['type'] = 'vless'
        outbound['uuid'] = parsed['credentials']
        if parsed.get('flow'):
            outbound['flow'] = parsed['flow']
    elif parsed['proto'] == 'trojan':
        outbound['type'] = 'trojan'
        outbound['password'] = parsed['credentials']

    security_mode = parsed.get('security_mode', 'none')
    if security_mode == 'xtls':
        outbound['xtls'] = {
            'enabled': True,
            'server_name': parsed.get('sni') or parsed.get('host', ''),
            'allow_insecure': True
        }
        if parsed.get('flow'):
            outbound['xtls']['flow'] = parsed.get('flow')
        if parsed.get('extra', {}).get('alpn'):
            outbound['xtls']['alpn'] = _parse_alpn(parsed['extra']['alpn'])
    elif parsed.get('is_tls'):
        outbound['tls'] = {
            'enabled': True,
            'server_name': parsed.get('sni') or parsed.get('host', ''),
            'insecure': True
        }
        if parsed.get('extra', {}).get('alpn'):
            outbound['tls']['alpn'] = _parse_alpn(parsed['extra']['alpn'])

    transport = build_singbox_transport(parsed)
    if transport:
        outbound['transport'] = transport

    config = {
        'log': {'level': 'panic'},
        'inbounds': [
            {
                'type': 'http',
                'listen': '127.0.0.1',
                'listen_port': local_port
            }
        ],
        'outbounds': [outbound]
    }
    return config
