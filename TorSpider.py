#!/usr/bin/env python
# -*- coding: utf-8 -*-

''' TorSpider – A script to explore the darkweb.
    -------------------by Christopher Steffen---
    
    Usage: TorSpider.py [Seed URL]
    
        If no Seed URL is provided, TorSpider will begin scanning wherever
        it left off last time, then will re-scan all known URLs from the top
        of the list.
    
    --------------------------------------------
    
    TorSpider will explore the darkweb to discover as many onion sites as
    possible, storing them all in a database along with whatever additional
    information can be found. It will also store data regarding which sites
    connected to which other sites, allowing for some relational mapping.
    
    The database generated by TorSpider will be accessible via a secondary
    script which will create a web interface for exploring the saved data.
'''

import requests, sys, sqlite3

# Just to prevent some SSL errors.
requests.packages.urllib3.util.ssl_.DEFAULT_CIPHERS += ':ECDHE-ECDSA-AES128-GCM-SHA256'

# Determine if the user has provided a Seed URL or asked for usage information.
seed_url = ''
try:
    seed_url = sys.argv[1]
except:
    pass
if(seed_url == '--help' or seed_url == '-h'):
    print '''
Usage: TorSpider.py [Seed URL]

    If no Seed URL is provided, TorSpider will begin scanning wherever
    it left off last time, then will re-scan all known URLs from the top
    of the list.
'''
    sys.exit(0)

# This function provides us with a connection routed through the Tor proxy.
def get_tor_session():
    session = requests.session()
    session.proxies = {'http': 'socks5://127.0.0.1:9050', 'https':'socks5://127.0.0.1:9050'}
    return session

session = get_tor_session()

# First, let's see if we're able to connect through Tor.
try:
    local_ip = requests.get('http://icanhazip.com').text
    tor_ip = session.get('http://icanhazip.com').text
    
    print "Local IP: %s" % (local_ip.strip())
    print "Tor IP:   %s" % (tor_ip.strip())
    if(local_ip != tor_ip):
        print "Tor connection successful!"
    else:
        print "Tor connection unsuccessful."
        sys.exit(0)
except:
    print "Tor connection unsuccessful."
    sys.exit(0)

# At this point, we have a successful Tor connection, and can begin the process of scanning.