import os, json, requests, types, re, time, copy, traceback, logging
from hysds.celery import app
import hysds_commons.action_utils
import hysds_commons.mozart_utils
import hysds_commons.job_rest_utils
from datetime import datetime

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("hysds")

user_name = None

def create_user_rules_index(es_url, es_index):
    """Create user rules index applying percolator mapping."""

    # create index with percolator mapping
    mapping_file = os.path.normpath(os.path.join(
        app.root_path, 'configs',
        'user_rules_dataset.mapping'))
    with open(mapping_file) as f:
        mapping = f.read()
    r = requests.put("%s/%s" % (es_url, es_index), data=mapping)
    r.raise_for_status()

def add_grq_mappings(es_url, es_index):
    """Add mappings from GRQ product indexes."""

    # get current mappings in user rules
    r = requests.get("%s/%s/_mapping" % (es_url, es_index))
    r.raise_for_status()
    user_rules_mappings = r.json()[es_index]['mappings']

    # get all mappings from GRQ product indexes using alias
    grq_index = app.conf['DATASET_ALIAS']
    r = requests.get("%s/%s/_mapping" % (es_url, grq_index))
    r.raise_for_status()
    mappings = r.json()
    for idx in mappings:
        for doc_type in mappings[idx]['mappings']:
            if doc_type not in user_rules_mappings:
                r = requests.put("%s/%s/_mapping/%s" % (es_url, es_index, doc_type),
                                 data=json.dumps(mappings[idx]['mappings'][doc_type]))
                r.raise_for_status()

def add_user_rule(projectName, rule_name, workflow, priority, query_string, other_params):
    """Add a user rule."""
    if 'lar' in workflow:
	queue = projectName+"-job_worker-large"
    elif 'email' in workflow:
	queue = "system-jobs-queue" 
    else:
    	queue = projectName+"-job_worker-small"

    if workflow is None:
        return json.dumps({
            'success': False,
            'message': "Workflow not specified.",
            'result': None,
        }), 500

    with open('_job.json') as f:
      ctx = json.load(f)

    user_name = ctx['username']

    # get es url and index
    es_url = app.conf['GRQ_ES_URL']
    es_index = app.conf['USER_RULES_DATASET_INDEX']

    # if doesn't exist, create index
    r = requests.get('%s/%s' % (es_url, es_index))
    if r.status_code == 404:
        create_user_rules_index(es_url, es_index)

    # ensure GRQ product index mappings exist in percolator index
    add_grq_mappings(es_url, es_index)

    # query
    query = {
        "query": {
            "bool": {
                "must": [
                    { "term": { "username": user_name }  },
                    { "term": { "rule_name": rule_name } },
                ]
            }
        }
    }
    r = requests.post('%s/%s/.percolator/_search' % (es_url, es_index), data=json.dumps(query))
    result = r.json()
    if r.status_code != 200:
        logger.debug("Failed to query ES. Got status code %d:\n%s" % 
                         (r.status_code, json.dumps(result, indent=2)))
    r.raise_for_status()
    if result['hits']['total'] == 1:
        logger.debug("Found a rule using that name already: %s" % rule_name)
        return json.dumps({
            'success': False,
            'message': "Found a rule using that name already: %s" % rule_name,
            'result': None,
        }), 500

    job_type = None
    passthru_query = False
    query_all = False
    print 'GRQ_ES_URL (iospec_es_url): %s   JOBS_ES_URL (jobspec_es_url): %s'%(app.conf["GRQ_ES_URL"],app.conf["JOBS_ES_URL"])
    for action in hysds_commons.action_utils.get_action_spec(app.conf["GRQ_ES_URL"],app.conf["JOBS_ES_URL"]):
	#print "Action from hysds_commons.action_utils.get_action_spec: %s"%action
        if action['type'] == workflow:
            job_type = action['job_type']
            passthru_query = action.get('passthru_query', False)
            query_all = action.get('query_all', False)
    if job_type is None: 
	print "No job_type find for '%s'." % workflow
        logger.debug("No job_type find for '%s'." % workflow)
        return json.dumps({
            'success': False,
            'message': "No job_type found for '%s'." % workflow,
            'result': None,
        }), 500

    time_now = datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ')    
    # upsert new document
    new_doc = {
        "workflow": workflow,
        "priority": priority,
        "rule_name": rule_name,
        "username": user_name,
        "query_string": query_string,
        "kwargs": json.dumps(other_params),
        "job_type": job_type,
        "enabled": True,
        "query": json.loads(query_string),
        "passthru_query": passthru_query,
        "query_all": query_all,
        "queue":queue,
        "creation_time":time_now,
        "modification_time":time_now
    }
    r = requests.post('%s/%s/.percolator/' % (es_url, es_index), data=json.dumps(new_doc))
    print "new_doc:\n"+json.dumps(new_doc)
    print 'Posting to %s/%s/.percolator/' % (es_url, es_index)
    result = r.json()
    if r.status_code != 201:
	print "Failed to insert new rule for %s. Got status code %d:\n%s"%(user_name, r.status_code, json.dumps(result, indent=2))
        logger.debug("Failed to insert new rule for %s. Got status code %d:\n%s" % 
                         (user_name, r.status_code, json.dumps(result, indent=2)))
    r.raise_for_status()
    
    return json.dumps({
        'success': True,
        'message': "",
        'result': result,
    })
