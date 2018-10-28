#!/usr/bin/env python

'''
This script is for stamping AOIs that have expired as inactive,
and send email to ops about all AOIs expiring in the next week.
This will be a cron job that runs once every day.
'''

import os
import logging
from hysds.celery import app
import json
import requests
import notify_by_email

#Setup logger for this job here.  Should log to STDOUT or STDERR as this is a job
logging.basicConfig(level=logging.DEBUG)
LOGGER = logging.getLogger("hysds")

BASE_PATH = os.path.dirname(__file__)

def email_to_ops(aoi_list, expired_aois):
    LOGGER.debug("\nNeed to send email to ops with list of expiring")
    print ("\nNeed to send email to ops with list of expiring")
    attachments = None
    bcc_recipients = ''
    cc_recipients = 'grfn-ops@jpl.nasa.gov'

    subject = "Test: Expiring AOIs"
    body = "Hi,\n"
    body += "\nBelow is the list of AOIs expiring within the next 7 days. \n"
    for aoi in aoi_list:
        body += aoi + '\n'
    body += "\nBelow is the list of AOIs that have been marked inactive (Not really. This is a test)\n"
    for aoi in expired_aois:
        body += aoi + '\n'

    body += "\nIf you have any questions, please email aria-help@jpl.nasa.gov\n"
    body += "Thanks,\n Aria"
    notify_by_email.send_email("noreply-hysds@jpl.nasa.gov", cc_recipients, bcc_recipients, subject, body, attachments)
    LOGGER.info("Email sent to %s", cc_recipients)
    print ("Email sent to %s", cc_recipients)

def get_url_index_type_id(_id):
    '''
    Returns the ES URL, index, doctype, and id of the given product
    @param product_id - id of the product to search for
    '''
    #_id = product_id
    query = {
        "query": {
            "bool": {
                "must": [
                    {"term": {"_id": _id}}
                ]
            }
        }
    }
    result = query_ES(query, True)
    es_url = app.conf['GRQ_ES_URL']
    _index = result[0]["_index"]
    _type = result[0]["_type"]
    _id = result[0]["_id"]
    return (es_url, _index, _type, _id)

def update_document(aoi_id):
    '''
    Update the AOI with inactive tag
    @param aoi_id - id of AOI being de activated
    '''

    new_doc = {
        "doc": {
            "metadata.user_tags": "inactive"
            },
        "doc_as_upsert": True
        }

    url = "{0}/{1}/{2}/{3}/_update".format(*get_url_index_type_id(aoi_id))
    #just for testing purposes. Created grq_v1.1.2_s1-ifg_test index. It is a copy of the ifg index.
    #url = "{0}/{1}/grq_v1.1.2_s1-ifg_test/{3}/_update".format(*get_url_index_type_id(_id))
    print "Updating: {0} with {1}".format(url, json.dumps(new_doc))
    req_result = requests.post(url, data=json.dumps(new_doc))
    if req_result.raise_for_status() is  None:
        return True
    else:
        print req_result.raise_for_status()
        return False

def query_aois_expiring_soon():
    #query for aoi to notify ops about
    query = {
        "query": {
            "bool": {
                "must": [
                    {
                        "term": {
                            "_type": "area_of_interest"
                        }
                    },
                    {
                        "range": {
                            "endtime": {
                                "lte": "now+7d",
                                "gte": "now-1d"
                                }
                            }
                        }
                    ]
                }
            },
        "filter": {
            "not": {
                "term": {
                    "metadata.user_tags": "inactive"
                    }
                }
            }
        }
    return query_ES(query, False)

def query_aois_to_deactivate():
    query = {
        "query": {
            "bool": {
                "must": [
                    {
                        "term": {
                            "_type": "area_of_interest"
                        }
                    },
                    {
                        "range": {
                            "endtime": {
                                "lte": "now-1d"
                                }
                            }
                        }
                    ]
                }
            },
        "filter": {
            "not": {
                "term": {
                    "metadata.user_tags": "inactive"
                    }
                }
            }
        }
    return query_ES(query, False)

def query_ES(query, multiple_recs_check):
    es_url = app.conf["GRQ_ES_URL"]
    es_index = "grq"
    url = "%s/%s/_search/" % (es_url, es_index)
    data = json.dumps(query, indent=2)
    print "Posting ES search: {0} with {1}".format(url, data)
    req_result = requests.post(url, data=data)
    req_result.raise_for_status()
    #print "Got: {0}".format(req_result.json())
    result = req_result.json()
    if multiple_recs_check is True:
        if len(result["hits"]["hits"]) == 0:
            raise Exception("Product not found in ES index")
        elif len(result["hits"]["hits"]) > 1:
            raise Exception("Product found multiple times")
    return result["hits"]["hits"]

def mark_aois_inactive():
    inactive_aois = []
    results = query_aois_to_deactivate()
    print "AOIs to deactivate:"
    for result in results:
        aoi_id = result["_id"]
        end_time = result["_source"]["endtime"]
        print aoi_id + ", endtime :- " + end_time
        inactive_aois.append(aoi_id + ", endtime :- " + end_time)
        update_document(aoi_id)
    return inactive_aois

def send_email_to_ops(inactive_aois):
    expiring_aois = []
    results = query_aois_expiring_soon()
    print "AOIs expiring in the next 7 days"
    for result in results:
        aoi_id = result["_id"]
        end_time = result["_source"]["endtime"]
        print aoi_id + ", endtime :- " + end_time
        expiring_aois.append(aoi_id + ", endtime :- " + end_time)
    #send email(body)
    email_to_ops(expiring_aois, inactive_aois)

if __name__ == "__main__":
    '''
    Main program to:
    1. Mark AOIs inactive
    2. Send email to ops with list of AOIs
       expiring within the next 7 days
    '''
    inactive_aois = mark_aois_inactive()
    send_email_to_ops(inactive_aois)
