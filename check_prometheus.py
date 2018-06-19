#!/usr/bin/env python

from __future__ import print_function

import argparse
import contextlib
import logging
import requests
import string
import sys
import traceback

METRICS=[]

def status(status, message, force_print=False):
    global STATUS
    if status in ('ok', 'warn', 'err'):
        raise ValueError('The status "%s" is not allowed because it creates a '
                         'metric called legacy_state' % status)
    status_line = 'status %s' % status
    if message is not None:
        status_line = ' '.join((status_line, str(message)))
    status_line = status_line.replace('\n', '\\n')
    STATUS = status_line
    if force_print:
        print(STATUS)

def status_ok(message=None, force_print=False, m_name=None):
    status('okay', message, force_print=force_print)

def status_err(message=None, force_print=False, exception=None, m_name=None):
    if exception:
        # a status message cannot exceed 256 characters
        # 'error ' plus up to 250 from the end of the exception
        message = message[-250:]
    status('error', message, force_print=force_print)
    if exception:
        raise exception
    sys.exit(1)


def metric(name, metric_type, value, unit=None, m_name=None, extra_msg=''):
    if len(METRICS) > 49:
        status_err('Maximum of 50 metrics per check', m_name='maas')

    metric_line = 'metric %s %s %s' % (name, metric_type, value)
    if unit is not None:
        metric_line = ' '.join((metric_line, unit))

    metric_line = metric_line.replace('\n', '\\n')
    METRICS.append(metric_line)

    if extra_msg:
        METRICS.append('metric msg string %s' % extra_msg)

def metric_bool(name, success, m_name=None):
    value = success and 1 or 0
    metric(name, 'uint32', value, m_name=m_name)

@contextlib.contextmanager
def print_output():
    try:
        yield
    except SystemExit as e:
        if STATUS:
            print(STATUS)
        raise
    except Exception as e:
        logging.exception('The plugin %s has failed with an unhandled '
                          'exception', sys.argv[0])
        status_err(traceback.format_exc(), force_print=True, exception=e,
                   m_name='maas')
    else:
        if STATUS:
            print(STATUS)
        for metric in METRICS:
            print(metric)

def check(args):
    check_name = 'maas_k8s_prometheus_%s' % args.check
    try:
        r = requests.get('%s/api/v1/query' % args.prometheus_endpoint,
                         params={'query': args.query},
                         timeout=5)

        if (r.status_code != 200):
            raise Exception("Prometheus returned status code %s" % str(
                r.status_code))
        res = r.json()

        if res['status'] != 'success':
            raise Exception("Prometheus returned status %s" % str(
                res['status']))

        value = 0
        targets = []
        if 'data' in res:
            res = res['data']
            if 'result' in res:
                res = res['result']

                for item in res:
                    # NOTE the actual value isn't what we're after -- all
                    # queries are simply counting the results.
                    value += 1

                    met = item['metric']

                    if 'nodename' in met:
                        target = met['nodename']
                    elif 'node' in met:
                        target = met['node']
                    elif 'container' in met:
                        target = '%s:%s (%s)' % (met['namespace'], met['pod'], met['container'])
                    else:
                        target = met['instance']

                    targets.append(target)

        metric(args.check, 'double', value, extra_msg=', '.join(targets))

    except (requests.HTTPError, requests.Timeout, requests.ConnectionError):
        metric_bool('client_success', False, m_name=check_name)
        # Any other exception presumably isn't an API error

    except Exception as e:
        metric_bool('client_success', False, m_name=check_name)
        status_err(str(e), m_name=check_name)
    else:
        metric_bool('client_success', True, m_name=check_name)

    status_ok(m_name=check_name)

def main(args):
    check(args)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Retrieve values for a check from the Prometheus API')
    parser.add_argument('prometheus_endpoint',
                        help="Prometheus endpoint url")
    parser.add_argument('--query',
                        default=None,
                        type=str,
                        help='the query for Prometheus')
    parser.add_argument('--check',
                        default=None,
                        type=str,
                        help='the name of the check')
    args = parser.parse_args()
    with print_output():
        main(args)
