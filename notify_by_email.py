#!/usr/bin/env python
import os
import sys
import getpass
import requests
import json
import types
import base64
from smtplib import SMTP
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email.header import Header
from email.utils import parseaddr, formataddr, COMMASPACE, formatdate
from email import encoders
from hysds.celery import app
from hysds_commons.net_utils import get_container_host_ip


def send_email(sender, cc_recipients, bcc_recipients, subject, body, attachments=None):
    """Send an email.

    All arguments should be Unicode strings (plain ASCII works as well).

    Only the real name part of sender and recipient addresses may contain
    non-ASCII characters.

    The email will be properly MIME encoded and delivered though SMTP to
    172.17.0.1.  This is easy to change if you want something different.

    The charset of the email will be the first one out of US-ASCII, ISO-8859-1
    and UTF-8 that can represent all the characters occurring in the email.
    """

    # combined recipients
    recipients = []
    recipients.extend([cc_recipients, bcc_recipients])

    # Header class is smart enough to try US-ASCII, then the charset we
    # provide, then fall back to UTF-8.
    header_charset = 'ISO-8859-1'

    # We must choose the body charset manually
    for body_charset in 'US-ASCII', 'ISO-8859-1', 'UTF-8':
        try:
            body.encode(body_charset)
        except UnicodeError:
            pass
        else:
            break

    # Split real name (which is optional) and email address parts
    sender_name, sender_addr = parseaddr(sender)
    parsed_cc_recipients = [parseaddr(rec) for rec in cc_recipients]
    parsed_bcc_recipients = [parseaddr(rec) for rec in bcc_recipients]
    #recipient_name, recipient_addr = parseaddr(recipient)

    # We must always pass Unicode strings to Header, otherwise it will
    # use RFC 2047 encoding even on plain ASCII strings.
    sender_name = str(Header(unicode(sender_name), header_charset))
    unicode_parsed_cc_recipients = []
    for recipient_name, recipient_addr in parsed_cc_recipients:
        recipient_name = str(Header(unicode(recipient_name), header_charset))
        # Make sure email addresses do not contain non-ASCII characters
        recipient_addr = recipient_addr.encode('ascii')
        unicode_parsed_cc_recipients.append((recipient_name, recipient_addr))
    unicode_parsed_bcc_recipients = []
    for recipient_name, recipient_addr in parsed_bcc_recipients:
        recipient_name = str(Header(unicode(recipient_name), header_charset))
        # Make sure email addresses do not contain non-ASCII characters
        recipient_addr = recipient_addr.encode('ascii')
        unicode_parsed_bcc_recipients.append((recipient_name, recipient_addr))

    # Make sure email addresses do not contain non-ASCII characters
    sender_addr = sender_addr.encode('ascii')

    # Create the message ('plain' stands for Content-Type: text/plain)
    msg = MIMEMultipart()
    msg['CC'] = COMMASPACE.join([formataddr((recipient_name, recipient_addr))
                                 for recipient_name, recipient_addr in unicode_parsed_cc_recipients])
    msg['FROM'] = "no-reply@jpl.nasa.gov"
    msg['TO'] = "grfn-ops@jpl.nasa.gov"
    msg['BCC'] = COMMASPACE.join([formataddr((recipient_name, recipient_addr))
                                  for recipient_name, recipient_addr in unicode_parsed_bcc_recipients])
    msg['Subject'] = Header(unicode(subject), header_charset)
    msg.attach(MIMEText(body.encode(body_charset), 'plain', body_charset))

    # Add attachments
    if isinstance(attachments, types.DictType):
        for fname in attachments:
            part = MIMEBase('application', "octet-stream")
            part.set_payload(attachments[fname])
            Encoders.encode_base64(part)
            part.add_header('Content-Disposition',
                            'attachment; filename="%s"' % fname)
            msg.attach(part)

    # print "#" * 80
    # print msg.as_string()

    # Send the message via SMTP to docker host
    smtp_url = "smtp://%s:25" % get_container_host_ip()
    print("smtp_url : %s", smtp_url)
    smtp = SMTP(get_container_host_ip())
    smtp.sendmail(sender, recipients, msg.as_string())
    smtp.quit()


def get_source(es_url, query_idx, objectid):
    """Return source metadata for objectid."""

    query = {
        "sort": {
            "_timestamp": {
                "order": "desc"
            }
        },
        "query": {
            "term": {
                "_id": objectid
            }
        }
    }
    print('get_source debug:', '%s/%s/_search', es_url,
          "    ", query_idx, '    ', json.dumps(query))
    r = requests.post('%s/%s/_search' %
                      (es_url, query_idx), data=json.dumps(query))
    r.raise_for_status()
    result = r.json()
    if result['hits']['total'] == 0:
        return None
    else:
        return result['hits']['hits'][0]['_source']


def get_cities(src):
    """Return list of cities."""

    cities = []
    for city in src.get('city', []):
        cities.append("%s, %s" %
                      (city.get('name', ''), city.get('admin1_name', '')))
    return cities


def get_value(d, key):
    """Return value from source based on key."""

    for k in key.split('.'):
        if k in d:
            d = d[k]
        else:
            return None
    if isinstance(d, types.ListType):
        return ', '.join([str(i) for i in d])
    else:
        return d


def get_metadata_snippet(src, snippet_cfg):
    """Return body text for metadata snippet."""

    body = ""
    for k, label in snippet_cfg:
        val = get_value(src, k)
        if val is not None:
            body += "%s: %s\n" % (label, val)
    body += "location type: %s\n" % src.get('location', {}).get('type', None)
    body += "location coordinates: %s\n" % src.get(
        'location', {}).get('coordinates', [])
    cities = get_cities(src)
    body += "Closest cities: %s" % "\n                ".join(cities)
    return body


def get_facetview_link(facetview_url, objectid, system_version=None):
    """Return link to objectid in FacetView interface."""

    if system_version is None:
        b64 = base64.urlsafe_b64encode(
            '{"query":{"query_string":{"query":"id:%s"}}}' % objectid)
    else:
        b64 = base64.urlsafe_b64encode(
            '{"query":{"query_string":{"query":"id:%s AND system_version:%s"}}}' % (objectid, system_version))
    return '%s/?base64=%s' % (facetview_url, b64)


if __name__ == "__main__":
    settings_file = os.path.normpath(
        os.path.join(
            os.path.dirname(os.path.realpath(__file__)),
            'settings.json')
    )
    settings = json.load(open(settings_file))

    objectid = sys.argv[1]
    url = sys.argv[2]
    emails = sys.argv[3]
    rule_name = sys.argv[4]
    component = sys.argv[5]

    if component == "mozart" or component == "figaro":
        es_url = app.conf["JOBS_ES_URL"]
        query_idx = app.conf["STATUS_ALIAS"]
        facetview_url = app.conf["MOZART_URL"]
    elif component == "tosca":
        es_url = app.conf["GRQ_ES_URL"]
        query_idx = app.conf["DATASET_ALIAS"]
        facetview_url = app.conf["GRQ_URL"]

    cc_recipients = [i.strip() for i in emails.split(',')]
    bcc_recipients = []
    subject = "[monitor] (notify_by_email:%s) %s" % (rule_name, objectid)
    body = "Product with id %s was ingested." % objectid
    attachments = None
    src = get_source(es_url, query_idx, objectid)
    if src is not None:
        # attach metadata json
        body += "\n\n%s" % get_metadata_snippet(src, settings['SNIPPET_CFG'])
        body += "\n\nThe entire metadata json for this product has been attached for your convenience.\n\n"
        attachments = {'metadata.json': json.dumps(src, indent=2)}

        # attach browse images
        if len(src['browse_urls']) > 0:
            browse_url = src['browse_urls'][0]
            if len(src['images']) > 0:
                body += "Browse images have been attached as well.\n\n"
                for i in src['images']:
                    small_img = i['small_img']
                    small_img_url = os.path.join(browse_url, small_img)
                    r = requests.get(small_img_url)
                    if r.status_code != 200:
                        continue
                    attachments[small_img] = r.content
    else:
        body += "\n\n"
    body += "You may access the product here:\n\n%s" % url
    facet_url = get_facetview_link(
        facetview_url, objectid, None if src is None else src.get('system_version', None))
    if facet_url is not None:
        body += "\n\nYou may view this product in FacetView here:\n\n%s" % facet_url
        body += "\n\nNOTE: You may have to cut and paste the FacetView link into your "
        body += "browser's address bar to prevent your email client from escaping the curly brackets."
    send_email(getpass.getuser(), cc_recipients, bcc_recipients,
               subject, body, attachments=attachments)
