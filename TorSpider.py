#!/usr/bin/env python3
# -*- coding: utf-8 -*-

''' ______________________________________________________________________
   |                         |                  |                         |
   |                   +-----^---TorSpider-v2---^-----+                   |
   |                   |  Crawling the Invisible Web  |                   |
   |                   +----------------by CMSteffen--+                   |
   |                                                                      |
   | TorSpider employs an army of spiders to explore Tor hidden services, |
   | seeking to uncover and catalogue the deepest reaches of the darknet. |
   | They are accompanied by Voltaire, their trusty historian and scribe, |
   | who chronicles their adventure with his sharp quill and sharper wit. |
    ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
'''

import os                    # +----------------------------------------+ #
import sys                   # |       Beware, ye who enter here:       | #
import time                  # |     The Invisible Web is rife with     | #
import random                # | wondrous and terrible things. It is no | #
import requests              # |  place for the squeamish or the faint  | #
import sqlite3 as sql        # |    of heart. Here there be dragons!    | #
from hashlib import sha1     # +----------------------------------------+ #
import multiprocessing as mp
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit

'''---[ GLOBAL VARIABLES ]---'''

# Should we log to the console?
log_to_console = True

# Let's use the default Tor Browser Bundle UA:
agent = 'Mozilla/5.0 (Windows NT 6.1; rv:52.0) Gecko/20100101 Firefox/52.0'

# Just to prevent some SSL errors.
requests.packages.urllib3.util.ssl_.DEFAULT_CIPHERS += \
                                              ':ECDHE-ECDSA-AES128-GCM-SHA256'


'''---[ CLASS DEFINITIONS ]---'''


class ParseLinks(HTMLParser):
    # Parse given HTML for all a.href links.
    def __init__(self):
        HTMLParser.__init__(self)
        self.output_list = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.output_list.append(dict(attrs).get('href'))


class ParseTitle(HTMLParser):
    def __init__(self):
        HTMLParser.__init__(self)
        self.match = False
        self.title = ''

    def handle_starttag(self, tag, attributes):
        self.match = True if tag == 'title' else False

    def handle_data(self, data):
        if self.match:
            self.title = data
            self.match = False


class Spider():
    def __init__(self, queue):
        self.queue = queue
        self.session = get_tor_session()

    def crawl(self):
        log("Ready to explore!")
        time_to_sleep = False
        while(not time_to_sleep):
            if(os.path.exists('sleep')):
                time_to_sleep = True
            else:

                # Query the database for a random link that hasn't been
                # scanned in 7 days or whose domain was marked offline more
                # than a day ago.
                query = self.db_get("SELECT domain, url FROM pages \
                              WHERE fault IS 'none' \
                              AND (date < DATETIME('now', '-7 day') \
                              OR domain IN (\
                                    SELECT id FROM onions \
                                    WHERE online IS '0' \
                                    AND date < DATETIME('now', '-1 day')\
                              )) ORDER BY RANDOM() LIMIT 1;")
                try:
                    (domain_id, url) = query[0]
                    url = self.fix_url(url)
                except Exception as e:
                    # No links to process. This should be rare...
                    time.sleep(10)
                    continue

                # Update the scan date for this page and domain.
                self.db_put("UPDATE pages SET date = ? \
                       WHERE url IS ? AND domain \
                       IS ?;", [get_timestamp(), url, domain_id])
                self.db_put("UPDATE onions SET date = ? \
                       WHERE id IS ?;", [get_timestamp(), domain_id])

                # Check to see if it's an http link.
                if(not self.is_http(url)):
                    # It's not.
                    self.db_put('UPDATE pages SET fault = ? \
                           WHERE url is ?;', ['non-http', url])
                    continue

                try:
                    # Retrieve the page's headers.
                    head = self.session.head(url)

                    # Did we get the page successfully?
                    if(head.status_code == 301):
                        # Moved permanently.
                        # If we can get the URL to the moved file, add it to
                        # the list of things to scan.
                        log("Moved permanently (301): {}".format(url))
                    elif(head.status_code == 302):
                        # The page was found...
                        # If we can get the URL to the moved file, add it to
                        # the list of things to scan.
                        log("Page found (302): {}".format(url))
                    elif(head.status_code == 303):
                        # See other.
                        # If we can get the URL to the moved file, add it to
                        # the list of things to scan.
                        log("See other (303): {}".format(url))
                    elif(head.status_code == 307):
                        # Temporary redirect.
                        # If we can get the URL to the moved file, add it to
                        # the list of things to scan.
                        log("Temporary redirect (307): {}".format(url))
                    elif(head.status_code == 400):
                        # Bad request.
                        log("Bad request (400): {}".format(url))
                        self.set_fault(url, '400')
                        continue
                    elif(head.status_code == 401):
                        # Unauthorized.
                        self.set_fault(url, '401')
                        continue
                    elif(head.status_code == 403):
                        # Forbidden.
                        self.set_fault(url, '403')
                        continue
                    elif(head.status_code == 404):
                        # This page doesn't exist. Avoid scanning it again.
                        self.set_fault(url, '404')
                        continue
                    elif(head.status_code == 405):
                        # Method not allowed.
                        self.set_fault(url, '405')
                        continue
                    elif(head.status_code == 500):
                        # The server had an error. This might not be our fault,
                        # but it might be best not to scan that page again.
                        self.set_fault(url, '500')
                        continue
                    elif(head.status_code == 502):
                        # Bad gateway.
                        self.set_fault(url, '502')
                        continue
                    elif(head.status_code == 503):
                        # Service temporarily unavailable. We won't update the
                        # page's status, because it might be available later.
                        continue
                    elif(head.status_code == 504):
                        # Gateway timeout. Again, don't change the page's
                        # status, because they might be available later.
                        self.set_fault(url, '504')
                    elif(head.status_code != 200):
                        # Unknown status. I'll add more status_code options
                        # as they arise.
                        self.set_fault(url, str(head.status_code))
                        log("Unknown status code {}: {}".format(
                                head.status_code, url))
                        continue

                    # Update the last_online date.
                    self.db_put('UPDATE onions SET last_online = ? \
                                WHERE id IS ?;', [get_timestamp(), domain_id])

                    content_type = self.get_type(head.headers)
                    # We only want to scan text for links. But if we don't
                    # know what the content type is, that might result
                    # from a redirection, so we'll scan it just in case.
                    if(content_type != 'text' and content_type is not None):
                        # Otherwise, if we know what it is, and it's not text,
                        # don't scan it.
                        self.set_fault(url, 'type: {}'.format(content_type))
                        continue

                    request = self.session.get(url)
                    if(content_type is None):
                        # We're going to process the request in the same way,
                        # because we couldn't get a content type from the head.
                        content_type = self.get_type(request.headers)
                        if(content_type != 'text'
                           and content_type is not None):
                            self.set_fault(url, 'type: {}'.format(
                                    content_type))
                            continue

                    # We've got the site's data. Let's see if it's changed...
                    try:
                        # Get the page's sha1 hash.
                        page_hash = self.get_hash(request.content)

                        # Retrieve the page's last hash.
                        query = self.db_get("SELECT hash FROM pages WHERE \
                                            domain IS ? AND url IS ?;",
                                            [domain_id, url])
                        last_hash = query[0][0]

                        # If the hash hasn't changed, don't process the page.
                        if(last_hash == page_hash):
                            continue

                        # Update the page's hash in the database.
                        self.db_put('UPDATE pages SET hash = ? \
                                    WHERE domain IS ? AND url IS ?;',
                                    [page_hash, domain_id, url])

                    except Exception as e:
                        log("Couldn't retrieve previous hash: {}".format(url))
                        continue

                    # The page's HTML changed since our last scan; let's
                    # process it.
                    page_text = request.text

                    # Get the title of the page.
                    try:
                        page_title = self.get_title(page_text)
                    except Exception as e:
                        log('Bad title: {}'.format(url))
                        self.db_put('UPDATE pages SET fault = ? \
                                    WHERE url IS ?;', ['bad title', url])
                        continue
                    self.db_put('UPDATE pages SET title = ? \
                                WHERE url IS ?;', [page_title, url])

                    # Get the page's links.
                    page_links = self.get_links(page_text, url)

                    # Add the links to the database.
                    for link_url in page_links:
                        # Get the link domain.
                        link_url = self.fix_url(link_url)
                        link_domain = self.get_domain(link_url)
                        try:
                            # Insert the new domain into the onions table.
                            self.db_put("INSERT OR IGNORE INTO onions \
                                        (domain) VALUES (?);", [link_domain])
                            # Insert the new link into the pages table.
                            self.db_put("INSERT OR IGNORE INTO pages \
                                        (domain, url) VALUES ( \
                                        (SELECT id FROM onions WHERE \
                                        domain = ?), ?);",
                                        [link_domain, link_url])
                            # Insert the new connection between domains.
                            self.db_put("INSERT OR IGNORE INTO links \
                                        (domain, link) \
                                        VALUES (?, (SELECT id FROM onions \
                                        WHERE domain = ?));",
                                        [domain_id, link_domain])
                        except Exception as e:
                            # There was an error saving the link to the
                            # database.
                            log("Couldn't add link to database: {}".format(
                                    e))
                            continue
                    # Parsing is complete for this page!
                except requests.exceptions.InvalidURL:
                    # The url provided was invalid.
                    log("Invalid URL: {}".format(url))
                    self.db_put('UPDATE pages SET fault = ? \
                                WHERE url IS ?;', ['invalid', url])

                except requests.exceptions.ConnectionError:
                    # We had trouble connecting to the url.
                    # First let's make sure we're still online.
                    try:
                        tor_ip = self.session.get('http://api.ipify.org/').text
                        # If we've reached this point, Tor is working.
                        # Set the domain to offline.
                        self.db_put("UPDATE onions SET online = '0' \
                                    WHERE id IS ?", [domain_id])
                        # Make sure we don't keep scanning the pages.
                        self.db_put("UPDATE pages SET date = ? \
                                    WHERE domain = ?;",
                                    [get_timestamp(), domain_id])
                    except Exception as e:
                        # We aren't connected to Tor for some reason.
                        log("I can't get online: {}".format(e))
                        # It might be a temporary outage, so let's wait
                        # for a little while and see if it fixes itself.
                        time.sleep(10)
                        continue

                except requests.exceptions.TooManyRedirects as e:
                    # Redirected too many times. Let's not keep trying.
                    self.db_put('UPDATE pages SET fault = ? \
                                WHERE url IS ?;', ['redirect', url])

                except requests.exceptions.ChunkedEncodingError as e:
                    # Server gave bad chunk. This might not be a permanent
                    # problem, so let's just roll with it.
                    continue

                except MemoryError as e:
                    # Whatever it is, it's way too big.
                    log('Ran out of memory: {}'.format(url))
                    self.db_put('UPDATE pages SET fault = ? \
                                WHERE url IS ?;', ['memory error', url])

                except NotImplementedError as e:
                    log("I don't know what this means: {} - {}".format(e, url))
        self.db_put('sleeping')  # Let the Scribe know we're going to sleep.
        log("Going to sleep!")

    def db_get(self, query, args=[]):
        # Request information from the database.
        connection = sql.connect('data/SpiderWeb.db')
        cursor = connection.cursor()
        while(True):
            try:
                cursor.execute(query, args)
                output = cursor.fetchall()
                connection.close()
                return output
            except Exception as e:
                if(e != 'database is locked'):
                    connection.close()
                    log("SQL Error: {}".format(
                            combine(query, args)))
                    return None
                else:
                    # Let's see if the database frees up.
                    time.sleep(0.1)

    def db_put(self, query, args=[]):
        # Add or change the information in the database.
        # Let's tell our scribe to handle this bit.
        self.queue.put((query, args))

    def defrag_domain(self, domain):
        # Defragment the given domain.
        domain_parts = domain.split('.')
        # Onion domains don't have strange symbols or numbers in them, so be
        # sure to remove any of those just in case someone's obfuscating
        # domains for whatever reason.
        domain_parts[-2] = ''.join(
                ch for ch in domain_parts[-2] if ch.isalnum())
        domain = '.'.join(domain_parts)
        return domain

    def fix_url(self, url):
        # Fix obfuscated urls.
        (scheme, netloc, path, query, fragment) = urlsplit(url)
        netloc = self.defrag_domain(netloc)
        url = urlunsplit((scheme, netloc, path, query, fragment))
        return url

    def get_domain(self, url):
        # Get the defragmented domain of the given url.
        domain = self.defrag_domain(urlsplit(url)[1])
        # Let's omit subdomains. Rather than having separate records for urls
        # like sub1.onionpage.onion and sub2.onionpage.onion, just keep them
        # all under onionpage.onion.
        domain = '.'.join(domain.split('.')[-2:])
        return domain

    def get_hash(self, data):
        # Get the sha1 hash of the provided data. Data must be binary-encoded.
        return sha1(data).hexdigest()

    def get_links(self, data, url):
        # Given HTML input, return a list of all unique links.
        parse = ParseLinks()
        parse.feed(data)
        links = []
        domain = urlsplit(url)[1]
        for link in parse.output_list:
            if(link is None):
                # Skip empty links.
                continue
            # Remove any references to the current directory. ('./')
            link = link.replace('./', '')
            # Split the link into its component parts.
            (scheme, netloc, path, query, fragment) = urlsplit(link)
            # Fill in empty schemes.
            scheme = 'http' if scheme is '' else scheme
            # Fill in empty paths.
            path = '/' if path is '' else path
            if(netloc is '' and '.onion' in path.split('/')[0]):
                # The urlparser mistook the domain as part of the path.
                netloc = path.split('/')[0]
                try:
                    path = '/'.join(path.split('/')[1:])
                except Exception as e:
                    path = '/'
            # Fill in empty domains.
            netloc = domain if netloc is '' else netloc
            fragment = ''
            if('.onion' not in netloc or '.onion.' in netloc):
                # We are only interested in links to other .onion domains,
                # and we don't want to include links to onion redirectors.
                continue
            links.append(urlunsplit((scheme, netloc, path, query, fragment)))
        # Make sure we don't return any duplicates!
        return unique(links)

    def get_title(self, data):
        # Given HTML input, return the title of the page.
        parse = ParseTitle()
        parse.feed(data)
        return parse.title.strip()

    def get_type(self, headers):
        # What's the content type of the page we're checking?
        content_type = None
        try:
            content_type = headers['Content-Type'].split('/')[0]
        except Exception as e:
            pass
        return content_type

    def is_http(self, url):
        # Determine whether the link is an http/https scheme or not.
        (scheme, netloc, path, query, fragment) = urlsplit(url)
        return True if 'http' in scheme else False

    def set_fault(self, url, fault):
        # Update the url's fault.
        self.db_put('UPDATE pages SET fault = ? \
               WHERE url IS ?;', [fault, url])


class Scribe():
    def __init__(self, queue):
        self.queue = queue

    def begin(self):
        log("I'm awake! Checking my database.")
        self.check_db()
        log("Okay, I'm ready.")
        num_spiders = mp.cpu_count() - 1
        num_spiders = num_spiders if num_spiders > 0 else 1
        spiders_sleeping = 0
        time_to_sleep = False
        while(not time_to_sleep):
            # As long as the scribe is awake, he'll keep processing the
            # messages provided.

            connection = sql.connect('data/SpiderWeb.db')
            cursor = connection.cursor()

            while(not self.queue.empty()):
                # Process all the messages in the queue.
                (message, args) = self.queue.get()  # Get the next message.
                executed = False

                if(message == 'sleeping'):
                    # Take note when a spider goes to sleep.
                    spiders_sleeping += 1
                    executed = True

                while(not executed):
                    # Let's keep trying until we successfully execute.
                    try:
                        # Execute the command.
                        cursor.execute(message, args)
                        executed = True
                    except Exception as e:
                        if(e != 'database is locked'):
                            log("SQL Error: {}".format(
                                    combine(message, args)))
                            # We don't need to keep retrying a broken SQL
                            # statement, so let's break the loop.
                            executed = True
                        else:
                            time.sleep(0.1)  # See if the database frees up.

            # Now commit those changes to the database.
            connection.commit()
            connection.close()

            if(os.path.exists('sleep') and spiders_sleeping == num_spiders):
                # All the spiders have gone to sleep, so should we.
                time_to_sleep = True
        log('Going to sleep!')

    def check_db(self):
        if(not os.path.exists('data/SpiderWeb.db')):
            log("Initializing new database...")

            # First, we'll set up the database structure.
            connection = sql.connect('data/SpiderWeb.db')
            cursor = connection.cursor()

            ''' Onions: Information about each individual onion domain.
                - id:           The numerical ID of that domain.
                - domain:       The domain itself (i.e. 'google.com').
                - online:       Whether the domain was online in the last scan.
                - last_online:  The last date the page was seen online.
                - date:         The date of the last scan.
                - info:         Any additional info known about the domain.
            '''
            cursor.execute("CREATE TABLE IF NOT EXISTS onions ( \
                            id INTEGER PRIMARY KEY, \
                            domain TEXT, \
                            online INTEGER DEFAULT '1', \
                            last_online DATETIME DEFAULT 'never', \
                            date DATETIME DEFAULT '1986-02-02 00:00:01', \
                            info TEXT DEFAULT 'none', \
                            CONSTRAINT unique_domain UNIQUE(domain));")

            ''' Pages: Information about each link discovered.
                - id:           The numerical ID of that page.
                - title:        The page's title.
                - domain:       The numerical ID of the page's parent domain.
                - url:          The URL for the page.
                - hash:         The page's sha1 hash, for detecting changes.
                - date:         The date of the last scan.
                - fault:        If there's a fault preventing scanning, log it.
            '''
            cursor.execute("CREATE TABLE IF NOT EXISTS pages ( \
                            id INTEGER PRIMARY KEY, \
                            title TEXT DEFAULT 'none', \
                            domain INTEGER, \
                            url TEXT, \
                            hash TEXT DEFAULT 'none', \
                            date DATETIME DEFAULT '1986-02-02 00:00:01', \
                            fault TEXT DEFAULT 'none', \
                            CONSTRAINT unique_page UNIQUE(domain, url));")

            ''' Links: Information about which domains connect to each other.
                - domain:       The numerical ID of the origin domain.
                - link:         The numerical ID of the target domain.
            '''
            cursor.execute('CREATE TABLE IF NOT EXISTS links ( \
                            domain INTEGER, \
                            link INTEGER, \
                            CONSTRAINT unique_link UNIQUE(domain, link));')

            # Next, we'll populate the database with some default values. These
            # pages are darknet indexes, so they should be a good starting
            # point.

            # The Uncensored Hidden Wiki
            # http://zqktlwi4fecvo6ri.onion/wiki/Main_Page
            cursor.execute("INSERT INTO onions (domain) VALUES ( \
                           'zqktlwi4fecvo6ri.onion');")
            cursor.execute("INSERT INTO pages (domain, url) VALUES ( \
                           '1', \
                           'http://zqktlwi4fecvo6ri.onion/wiki/Main_Page');")

            # OnionDir
            # http://auutwvpt2zktxwng.onion/index.php
            cursor.execute("INSERT INTO onions (domain) VALUES ( \
                           'auutwvpt2zktxwng.onion');")
            cursor.execute("INSERT INTO pages (domain, url) VALUES ( \
                           '2', \
                           'http://auutwvpt2zktxwng.onion/index.php');")

            # Wiki links
            # http://wikilink77h7lrbi.onion/
            cursor.execute("INSERT INTO onions (domain) VALUES ( \
                           'wikilink77h7lrbi.onion');")
            cursor.execute("INSERT INTO pages (domain, url) VALUES ( \
                           '3', \
                           'http://wikilink77h7lrbi.onion/');")

            # Deep Web Links
            # http://wiki5kauuihowqi5.onion/
            cursor.execute("INSERT INTO onions (domain) VALUES ( \
                           'wiki5kauuihowqi5.onion');")
            cursor.execute("INSERT INTO pages (domain, url) VALUES ( \
                           '4', \
                           'http://wiki5kauuihowqi5.onion/');")

            # OnionDir Deep Web Directory
            # http://dirnxxdraygbifgc.onion/
            cursor.execute("INSERT INTO onions (domain) VALUES ( \
                           'dirnxxdraygbifgc.onion');")
            cursor.execute("INSERT INTO pages (domain, url) VALUES ( \
                           '5', \
                           'http://dirnxxdraygbifgc.onion/');")

            # The Onion Crate
            # http://7cbqhjnlkivmigxf.onion/
            cursor.execute("INSERT INTO onions (domain) VALUES ( \
                           '7cbqhjnlkivmigxf.onion');")
            cursor.execute("INSERT INTO pages (domain, url) VALUES ( \
                           '6', \
                           'http://7cbqhjnlkivmigxf.onion/');")

            # Fresh Onions
            # http://zlal32teyptf4tvi.onion/
            cursor.execute("INSERT INTO onions (domain) VALUES ( \
                           'zlal32teyptf4tvi.onion');")
            cursor.execute("INSERT INTO pages (domain, url) VALUES ( \
                           '7', \
                           'http://zlal32teyptf4tvi.onion/');")

            connection.commit()
            connection.close()

            log("Database initialized.")
        else:
            # The database already exists.
            log("Database loaded.")


'''---[ FUNCTION DEFINITIONS ]---'''


def combine(message, args=[]):
    while(len(args) > 0):
        message = message.replace('?', args.pop(0), 1)
    return message


def get_timestamp():
    # Get a time stamp that fits Sqlite3's DATETIME format.
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def get_tor_session():
    # Create a session that's routed through Tor.
    session = requests.session()
    session.headers.update({'User-Agent': agent})
    session.proxies = {
            'http':  'socks5h://127.0.0.1:9050',
            'https': 'socks5h://127.0.0.1:9050'
        }
    return session


def log(line):
    if(log_to_console):
        # Print to the screen if log_to_console is enabled.
        print('{}| {}: {}'.format(
                get_timestamp(),
                mp.current_process().name,
                line))
    # Append the message to the logfile.
    f = open('spider.log', 'a')
    f.write("{}\n".format(line))
    f.close()


def unique(items):
    # Return the same list without duplicates)
    return list(set(items))


'''---[ SCRIPT ]---'''

if __name__ == '__main__':
    log('-' * 20)
    log('TorSpider v2 Initializing...')

    # If the data directory doesn't exist, create it.
    if(not os.path.exists('data')):
        try:
            os.mkdir('data')
        except Exception as e:
            log('Failed to create data directory: {}'.format(e))
            log('-' * 20)
            sys.exit(0)

    # Create a Tor session and check if it's working.
    log("Establishing Tor connection...")
    session = get_tor_session()
    try:
        local_ip = requests.get('http://api.ipify.org/').text
        tor_ip = session.get('http://api.ipify.org/').text
        if(local_ip == tor_ip):
            log("Tor connection failed: IPs match.")
            log('-' * 20)
            sys.exit(0)
        else:
            log("Tor connection established.")
    except Exception as e:
        log("Tor connection failed: {}".format(e))
        log('-' * 20)
        sys.exit(0)

    log('Waking the Scribe...')
    queue = mp.Queue()
    Voltaire = Scribe(queue)
    Voltaire_Process = mp.Process(target=Voltaire.begin)
    Voltaire_Process.name = 'Voltaire'
    Voltaire_Process.start()

    # Wait for the database to be created.
    while(not os.path.exists('data/SpiderWeb.db')):
        time.sleep(1)

    Spiders = []
    Spider_Procs = []

    log('Waking the Spiders...')
    # There are enough names here for a 32-core processor.
    names = ['Webster', 'Spinette', 'Crowley', 'Leggy',
             'Harry', 'Terry', 'Aunt Tula', 'Jumpy',
             'Wolf', 'Bubbles', 'Bitsy', 'Itsy',
             'Squatch', 'Cheryl', 'Trudy', 'Nancy',
             'Lester', 'Ginny', 'Gunther', 'Vinny',
             'Ronald', 'Gardenia', 'Frank', 'Casper',
             'Chester', 'Maude', 'Denny', 'Hank',
             'Bruce', 'Uma', 'Lizzy', 'Dizzy']
    count = mp.cpu_count() - 1
    count = count if count > 0 else 1
    for x in range(count):
        spider = Spider(queue)
        spider_proc = mp.Process(target=spider.crawl)
        random.shuffle(names)
        spider_proc.name = names.pop()
        Spider_Procs.append(spider_proc)
        Spiders.append(spider)
        spider_proc.start()
        # We make them sleep a second so they don't all go skittering after
        # the same URL at the same time.
        time.sleep(1)

    for spider_proc in Spider_Procs:
        spider_proc.join()

    Voltaire_Process.join()
    try:
        os.unlink('sleep')
    except Exception as e:
        pass
    log('The Spiders and Scribe gone to sleep. ZzZzz...')
    log('-' * 20)
