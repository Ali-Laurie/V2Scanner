import base64
import ipaddress
import json
import re
import urllib.request
from urllib.parse import urlparse, unquote, parse_qs

MAX_SUBSCRIPTION_BYTES = 5 * 1024 * 1024


def _is_ip_literal(value):
    if not value:
        return False
    try:
        ipaddress.ip_address(value.strip('[]'))
        return True
    except ValueError:
        return False

SUPPORTED_PROTOCOLS = ('vmess', 'vless', 'trojan', 'ss', 'hysteria', 'hysteria2', 'tuic', 'anytls', 'wireguard', 'socks', 'http')
LINK_RE = re.compile(r'(vmess://[^\s\'\"]+|vless://[^\s\'\"]+|trojan://[^\s\'\"]+|ss://[^\s\'\"]+|hysteria2://[^\s\'\"]+|hy2://[^\s\'\"]+|hysteria://[^\s\'\"]+|tuic://[^\s\'\"]+|anytls://[^\s\'\"]+|wireguard://[^\s\'\"]+|socks://[^\s\'\"]+|http://[^\s\'\"]+)')
UUID_RE = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
SUPPORTED_SS_METHODS = {
    'aes-128-gcm', 'aes-192-gcm', 'aes-256-gcm',
    'chacha20-ietf-poly1305', 'xchacha20-ietf-poly1305',
    'aes-128-cfb', 'aes-192-cfb', 'aes-256-cfb',
    'des-cfb', 'rc4-md5', 'rc4', 'aes-128-ctr',
}


def _qget(q, *keys):
    for k in keys:
        vals = q.get(k)
        if vals and vals[0]:
            return vals[0]
    return ''


def try_decode_base64_content(content):
    clean_content = re.sub(r'\s+', '', content)
    if not clean_content:
        return content
    try:
        missing_padding = len(clean_content) % 4
        if missing_padding:
            clean_content += '=' * (4 - missing_padding)
        decoded = base64.b64decode(clean_content).decode('utf-8', errors='ignore')
        if LINK_RE.search(decoded):
            return decoded
        return content
    except Exception:
        return content


def extract_links(text):
    text = text.strip()
    if not text:
        return []
    normalized = text.replace('\r', ' ').replace('\n', ' ')
    links = LINK_RE.findall(normalized)
    return [link.strip() for link in links if link.strip()]


def extract_links_from_json(payload):
    links = []
    if isinstance(payload, str):
        links.extend(extract_links(payload))
    elif isinstance(payload, dict):
        for value in payload.values():
            links.extend(extract_links_from_json(value))
    elif isinstance(payload, list):
        for item in payload:
            links.extend(extract_links_from_json(item))
    return list(dict.fromkeys([link for link in links if link]))


def fetch_subscription_source(source):
    try:
        scheme = urlparse(source).scheme.lower()
        if scheme not in ('http', 'https'):
            return []
        with urllib.request.urlopen(source, timeout=15) as response:
            raw = response.read(MAX_SUBSCRIPTION_BYTES)
            text = raw.decode('utf-8', errors='ignore')
            decoded = try_decode_base64_content(text)
            links = extract_links(decoded)
            if links:
                return links
            return extract_links_from_json(json.loads(decoded)) if decoded else []
    except Exception:
        return []


def resolve_source(source):
    source = source.strip()
    if not source:
        return []

    if source.lower().startswith(('http://', 'https://')):
        links = fetch_subscription_source(source)
        if links:
            return links

    if LINK_RE.search(source):
        return extract_links(source)

    decoded = try_decode_base64_content(source)
    if decoded != source:
        links = extract_links(decoded)
        if links:
            return links
        try:
            return extract_links_from_json(json.loads(decoded))
        except Exception:
            pass

    try:
        return extract_links_from_json(json.loads(source))
    except Exception:
        return []


def parse_vmess(link):
    try:
        raw_b64 = link[8:].split('#')[0].split('?')[0]
        raw_b64 = re.sub(r'\s+', '', raw_b64)
        missing_padding = len(raw_b64) % 4
        if missing_padding:
            raw_b64 += '=' * (4 - missing_padding)

        raw = base64.b64decode(raw_b64).decode('utf-8', errors='ignore')
        data = json.loads(raw)

        host = data.get('add')
        port = data.get('port')
        remark = data.get('ps', '')
        if port is not None:
            port = int(port)

        tls_val = str(data.get('tls', '')).lower()
        security_mode = tls_val if tls_val in ['tls', 'xtls'] else ('tls' if port == 443 else 'none')
        is_tls = security_mode in ['tls', 'xtls']
        sni = data.get('sni') or data.get('host') or ('' if _is_ip_literal(host) else host)

        credentials = data.get('id')
        transport_type = data.get('net', data.get('type', 'tcp')).lower()
        path = data.get('path', '')
        host_header = data.get('host', '')
        flow = data.get('flow', '')

        extra = {
            'fp': data.get('fp', ''),
            'alpn': data.get('alpn', ''),
            'pbkdf2': data.get('pbkdf2', ''),
            'mode': data.get('mode', ''),
            'headerType': data.get('headerType', ''),
            'key': data.get('key', ''),
            'serviceName': data.get('serviceName', ''),
            'obfs': data.get('obfs', ''),
            'protocol': data.get('protocol', ''),
            'auth': data.get('auth', ''),
            'up': data.get('up', ''),
            'down': data.get('down', ''),
            'peer': data.get('peer', ''),
        }
        extra = {k: v for k, v in extra.items() if v}

        return {
            'proto': 'vmess',
            'host': host,
            'port': port,
            'remark': remark,
            'is_tls': is_tls,
            'security_mode': security_mode,
            'sni': sni,
            'credentials': credentials,
            'transport_type': transport_type,
            'path': path,
            'host_header': host_header,
            'flow': flow,
            'extra': extra
        }
    except Exception:
        return None


def parse_generic(link):
    try:
        main_part = link.split('#')[0]
        remark = unquote(link.split('#')[-1]) if '#' in link else ''
        p = urlparse(main_part)
        proto = p.scheme.lower()
        if proto == 'hy2':
            proto = 'hysteria2'
        if proto not in SUPPORTED_PROTOCOLS:
            return None

        host = p.hostname
        port = p.port
        credentials = ''
        transport_type = 'tcp'
        path = ''
        host_header = ''

        if proto == 'ss':
            if not host or not port:
                raw_b64 = main_part[5:].split('?')[0]
                raw_b64 = re.sub(r'\s+', '', raw_b64)
                if '@' in raw_b64:
                    userinfo_b64, hostport = raw_b64.split('@', 1)
                    if ':' in hostport:
                        host, port = hostport.split(':', 1)
                        port = int(port)
                    try:
                        missing_padding = len(userinfo_b64) % 4
                        if missing_padding:
                            userinfo_b64 += '=' * (4 - missing_padding)
                        credentials = base64.b64decode(userinfo_b64).decode('utf-8', errors='ignore')
                    except Exception:
                        credentials = ''
                else:
                    try:
                        missing_padding = len(raw_b64) % 4
                        if missing_padding:
                            raw_b64 += '=' * (4 - missing_padding)
                        decoded = base64.b64decode(raw_b64).decode('utf-8', errors='ignore')
                        if '@' in decoded:
                            userinfo, hostport = decoded.split('@', 1)
                            if ':' in hostport:
                                host, port = hostport.split(':', 1)
                                port = int(port.split('/', 1)[0])
                            credentials = userinfo
                    except Exception:
                        credentials = ''
            else:
                if p.password is not None:
                    credentials = '{}:{}'.format(unquote(p.username or ''), unquote(p.password or ''))
                else:
                    userinfo = unquote(p.username or '')
                    if ':' in userinfo:
                        credentials = userinfo
                    else:
                        try:
                            raw = p.username or ''
                            missing_padding = len(raw) % 4
                            if missing_padding:
                                raw += '=' * (4 - missing_padding)
                            decoded = base64.b64decode(raw).decode('utf-8', errors='ignore')
                            credentials = decoded if ':' in decoded else userinfo
                        except Exception:
                            credentials = userinfo
        elif proto in ('socks', 'http'):
            if p.password is not None:
                credentials = '{}:{}'.format(unquote(p.username or ''), unquote(p.password or ''))
            else:
                userinfo = unquote(p.username or '')
                if ':' in userinfo:
                    credentials = userinfo
                elif userinfo:
                    try:
                        raw = p.username or ''
                        missing_padding = len(raw) % 4
                        if missing_padding:
                            raw += '=' * (4 - missing_padding)
                        decoded = base64.b64decode(raw).decode('utf-8', errors='ignore')
                        credentials = decoded if ':' in decoded else ''
                    except Exception:
                        credentials = ''
                else:
                    credentials = ''
        elif proto == 'hysteria2':
            if p.password is not None:
                credentials = '{}:{}'.format(unquote(p.username or ''), unquote(p.password or ''))
            else:
                credentials = unquote(p.username or '')
        elif proto == 'hysteria':
            credentials = unquote(p.username or '') or (unquote(p.password or '') if p.password is not None else '')
        elif proto == 'tuic':
            uuid_val = unquote(p.username or '')
            pw_val = unquote(p.password or '') if p.password is not None else ''
            credentials = pw_val or uuid_val
        elif proto == 'anytls':
            if p.password is not None:
                credentials = '{}:{}'.format(unquote(p.username or ''), unquote(p.password or ''))
            else:
                credentials = unquote(p.username or '')
        elif proto == 'wireguard':
            credentials = unquote(p.username or '')
        else:
            credentials = unquote(p.username or '')
            if proto == 'trojan' and not credentials:
                credentials = unquote(p.password or '')

        if port is not None:
            port = int(port)

        q = parse_qs(p.query)
        security_mode = q.get('security', [''])[0].lower()
        if security_mode == '' and proto == 'trojan':
            security_mode = 'tls'
        if security_mode == '' and proto in ('vless', 'trojan') and port == 443:
            security_mode = 'tls'
        if security_mode == '' and proto in ('hysteria', 'hysteria2', 'tuic', 'anytls'):
            security_mode = 'tls'

        is_tls = security_mode in ('tls', 'xtls')
        
        # Fix: Safely extract transport_type from parse_qs result
        type_val = q.get('type', [''])[0] or q.get('network', [''])[0] or q.get('protocol', ['tcp'])[0]
        transport_type = type_val.lower() if type_val else 'tcp'
        if proto in ('hysteria', 'hysteria2') and not type_val:
            transport_type = q.get('protocol', ['udp'])[0].lower()

        if transport_type == 'grpc':
            path = q.get('serviceName', [''])[0]
        else:
            path = q.get('path', [''])[0] or q.get('dest', [''])[0] or q.get('peer', [''])[0]

        host_header = q.get('host', [''])[0]
        flow = q.get('flow', [''])[0]
        alpn = q.get('alpn', [''])[0]
        fp = q.get('fp', [''])[0]
        pbk = q.get('pbk', [''])[0]
        pbkdf2 = q.get('pbkdf2', [''])[0]
        mode = q.get('mode', [''])[0]
        header_type = q.get('headerType', q.get('header-type', ['']))[0]
        key = q.get('key', [''])[0]
        service_name = q.get('serviceName', [''])[0]
        obfs = q.get('obfs', [''])[0]
        auth = q.get('auth', [''])[0]
        up = q.get('up', [''])[0]
        down = q.get('down', [''])[0]
        peer = q.get('peer', [''])[0]
        insecure = q.get('insecure', [''])[0]
        short_id = q.get('sid', [''])[0]
        spider_x = q.get('spx', [''])[0]
        plugin = q.get('plugin', [''])[0]
        obfs_password = _qget(q, 'obfs-password', 'obfs_password', 'obfsParam')
        congestion_control = _qget(q, 'congestion_control', 'congestion', 'congestion-control')
        udp_relay_mode = _qget(q, 'udp_relay_mode', 'udp-relay-mode')
        up_mbps = _qget(q, 'upmbps', 'up_mbps', 'up-mbps')
        down_mbps = _qget(q, 'downmbps', 'down_mbps', 'down-mbps')

        if proto == 'hysteria' and not credentials:
            credentials = auth

        extra = {
            'alpn': alpn,
            'fp': fp,
            'pbk': pbk,
            'pbkdf2': pbkdf2,
            'mode': mode,
            'headerType': header_type,
            'key': key,
            'serviceName': service_name,
            'obfs': obfs,
            'auth': auth,
            'up': up,
            'down': down,
            'peer': peer,
            'protocol': q.get('protocol', [''])[0],
            'insecure': insecure,
            'sid': short_id,
            'spx': spider_x,
            'plugin': plugin,
        }
        extra = {k: v for k, v in extra.items() if v}

        if proto == 'hysteria2':
            if credentials:
                extra['password'] = credentials
                extra['auth'] = credentials
            if obfs_password:
                extra['obfs_password'] = obfs_password
        elif proto == 'hysteria':
            if credentials or auth:
                extra['auth'] = credentials or auth
            if up_mbps:
                extra['up_mbps'] = up_mbps
            if down_mbps:
                extra['down_mbps'] = down_mbps
        elif proto == 'tuic':
            uuid_val = unquote(p.username or '')
            pw_val = unquote(p.password or '') if p.password is not None else ''
            if uuid_val:
                extra['uuid'] = uuid_val
            if pw_val:
                extra['password'] = pw_val
            if congestion_control:
                extra['congestion_control'] = congestion_control
            if udp_relay_mode:
                extra['udp_relay_mode'] = udp_relay_mode
        elif proto == 'anytls':
            if credentials:
                extra['password'] = credentials
        elif proto == 'wireguard':
            pk = credentials or _qget(q, 'privateKey', 'private_key', 'pk', 'secret')
            peer = _qget(q, 'publickey', 'public_key', 'peer_public_key', 'peerPublicKey', 'pubkey', 'peer')
            addr = _qget(q, 'address', 'addresses', 'ip')
            if pk:
                extra['private_key'] = pk
            if peer:
                extra['peer_public_key'] = peer
            if addr:
                extra['address'] = addr
            if not pk and not peer:
                return None

        sni = q.get('sni', [''])[0] or host_header or ('' if _is_ip_literal(host) else host)

        return {
            'proto': proto,
            'host': host,
            'port': port,
            'remark': remark,
            'is_tls': is_tls,
            'security_mode': security_mode or ('tls' if is_tls else 'none'),
            'sni': sni,
            'credentials': credentials,
            'transport_type': transport_type,
            'path': path,
            'host_header': host_header,
            'flow': flow,
            'extra': extra
        }
    except Exception as e:
        return None


def validate_parsed_config(parsed):
    if not parsed:
        return False, 'Invalid config format'

    if parsed.get('proto') not in SUPPORTED_PROTOCOLS:
        return False, 'Unsupported protocol'

    host = parsed.get('host')
    port = parsed.get('port')
    if not host or not port:
        return False, 'Missing host or port'
    if not isinstance(port, int) or port <= 0 or port > 65535:
        return False, 'Invalid port'

    proto = parsed['proto']
    credentials = parsed.get('credentials') or ''
    if proto in ('vmess', 'vless'):
        if not credentials or not UUID_RE.match(credentials):
            return False, 'Invalid UUID for vmess/vless'
    elif proto == 'trojan':
        if not credentials:
            return False, 'Missing trojan password'
    elif proto == 'ss':
        if ':' not in credentials:
            return False, 'Shadowsocks credentials must be method:password'
        method, password = credentials.split(':', 1)
        if not password:
            return False, 'Missing shadowsocks password'
        if method.lower() not in SUPPORTED_SS_METHODS:
            return False, f'Unsupported ss method: {method}'
    elif proto in ('hysteria', 'hysteria2'):
        if not credentials:
            return False, 'Missing hysteria password/auth'
        if parsed.get('transport_type') not in ('tcp', 'udp', 'ws'):
            return False, 'Unsupported hysteria transport type'
    elif proto == 'tuic':
        extra = parsed.get('extra') or {}
        if not extra.get('uuid'):
            return False, 'Missing tuic uuid'
        if not credentials:
            return False, 'Missing tuic password'
    elif proto == 'anytls':
        if not credentials:
            return False, 'Missing anytls password'
    elif proto == 'wireguard':
        extra = parsed.get('extra') or {}
        if not extra.get('private_key') and not extra.get('peer_public_key'):
            return False, 'Missing wireguard key material'

    if parsed.get('security_mode') == 'xtls' and proto not in ('vless',):
        return False, 'XTLS is only supported for VLESS in this parser'

    return True, None


def parse_link(link):
    link = link.strip()
    if not link:
        return None
    if link.startswith('vmess://'):
        return parse_vmess(link)
    return parse_generic(link)
