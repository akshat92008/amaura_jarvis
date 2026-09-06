def parse_url(url: str) -> dict:
    # Initialize result dictionary with default values
    result = {
        'scheme': '',
        'host': '',
        'port': None,
        'path': '',
        'query_params': {}
    }

    # Split the URL into scheme and the rest
    if '://' in url:
        scheme, rest = url.split('://', 1)
        result['scheme'] = scheme
    else:
        rest = url

    # Split the rest into host/port and path/query
    if '/' in rest:
        host_port, path_query = rest.split('/', 1)
        result['path'] = '/' + path_query.split('?')[0]
    else:
        host_port = rest
        result['path'] = '/'

    # Split host and port
    if ':' in host_port:
        host, port = host_port.split(':', 1)
        result['host'] = host
        result['port'] = int(port)
    else:
        result['host'] = host_port

    # Parse query parameters
    if '?' in rest:
        query_string = rest.split('?')[1]
        if '=' in query_string:
            pairs = query_string.split('&')
            for pair in pairs:
                if '=' in pair:
                    key, value = pair.split('=', 1)
                    result['query_params'][key] = value

    return result

# Example usage
if __name__ == '__main__':
    test_url = 'https://example.com:8080/path/to/resource?param1=value1&param2=value2'
    parsed = parse_url(test_url)
    print(parsed)