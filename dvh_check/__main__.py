#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sun Nov 18 2018
@author: Dan Cutright, PhD
This is the main python file for command line implementation.
"""

import os
from subprocess import call
import argparse
# from utilities import save_ip_and_port, load_ip_and_port, initialize_directories_settings


SCRIPT_DIR = os.path.dirname(__file__)

# initialize_directories_settings()


def main():
    parser = argparse.ArgumentParser(description='Command line interface for DanCheck')
    parser.add_argument('--host',
                        dest='host',
                        help='Allows Bokeh server to accept a non-default origin',
                        default=None)
    parser.add_argument('--port',
                        dest='port',
                        help='Initializes Bokeh server on a non-default port',
                        default=None)
    # parser.add_argument('--save-ip-and-port',
    #                     help='Save the ip and port in this call as defaults',
    #                     dest='save_ip_and_port',
    #                     default=False,
    #                     action='store_true')
    args = parser.parse_args()

    command = ["bokeh", "serve"]

    # ip_and_port = load_ip_and_port()
    # host, port = ip_and_port['host'], ip_and_port['port']
    host, port = 'localhost', '5006'

    if args.host:
        host = args.host

    if args.port:
        port = args.port

    if args.save_ip_and_port:
        # save_ip_and_port({'host': host, 'port': port})
        pass

    command.append("--allow-websocket-origin")
    command.append("%s:%s" % (host, port))
    command.append("--port")
    command.append(port)

    command.append(SCRIPT_DIR)

    call(command)


if __name__ == '__main__':
    main()
