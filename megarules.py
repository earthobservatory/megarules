from builtins import str
import json, getpass, requests
import logging
import sys, os, datetime
import hysds_commons.request_utils
import hysds_commons.metadata_rest_utils
import osaka.main
from string import Template
from hysds.celery import app
import add_user_rules
import notify_by_email 
import datetime
from dateutil.parser import parse


#Setup logger for this job here.  Should log to STDOUT or STDERR as this is a job
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("hysds")

#manually update this block when there is unsync with avaliable version of email and slcp product version
notify_by_email_io = "hysds-io-lw-tosca-notify-by-email"
email_job_version = "release-20170510"
admin_email = "grfn-ops@jpl.nasa.gov"
slcp_product_version = "v1.2" #look at ariamh/conf/dataset_versions.json under the correct release version
user_name = None
name = None
BASE_PATH = os.path.dirname(__file__)


def submit_jobs(job_name, job_type, release, job_params, condition, dataset_tag):
    # submit mozart job
    MOZART_URL = app.conf['MOZART_URL']
    job_submit_url = '%s/mozart/api/v0.1/job/submit' % MOZART_URL

    job_params["query"] = {"query": json.loads(condition)}
    job = job_type[job_type.find("hysds-io-")+9:]
    params = {}
    if 'acq' in job_type:
        # for acq submitter and acq localizer
        params["queue"] = "factotum-job_worker-small"
    else:
        params["queue"] = "aria-job_worker-small"
    params["priority"] = "5"
    params["name"] = job_name
    params["tags"] = '["%s"]' % dataset_tag
    params["type"] = 'job-%s:%s' % (job, release)
    params["params"] = json.dumps(job_params)
    params["enable_dedup"] = False
    print('submitting jobs with params:')
    print(json.dumps(params, sort_keys=True,indent=4, separators=(',', ': ')))
    r = requests.post(job_submit_url, data=params, verify=False)
    if r.status_code != 200:
        r.raise_for_status()
    result = r.json()
    if 'result' in list(result.keys()) and 'success' in list(result.keys()):
        if result['success']:
            job_id = result['result']
            print('submitted create_aoi:{} job: {} job_id: {}'.format(release, job, job_id))
        else:
            print('job not submitted successfully: {}'.format(result))
            raise Exception('job not submitted successfully: {}'.format(result))
    else:
        raise Exception('job not submitted successfully: {}'.format(result))

def get_AOI(AOI_name):
    logger.debug("Going to query ES for AOI")
    es_url = app.conf["GRQ_ES_URL"]
    index = app.conf["DATASET_ALIAS"]
    query_string = {"query":{"bool": {"must": [{"term": {"dataset_type.raw": "area_of_interest"}},{"query_string": {"query": '_id:"AOI"',"default_operator": "OR"}}]}}}
    query_string["query"]["bool"]["must"][1]["query_string"]["query"] = '_id:"'+AOI_name+'"'
    r = requests.post('%s/%s/_search?' % (es_url, index), json.dumps(query_string))
    return r

def query_es(query):
    """Query ES."""

    es_url = app.conf.GRQ_ES_URL
    rest_url = es_url[:-1] if es_url.endswith('/') else es_url
    url = "{}/_search?search_type=scan&scroll=60&size=100".format(rest_url)
    #logger.info("url: {}".format(url))
    r = requests.post(url, data=json.dumps(query))
    #r.raise_for_status()
    scan_result = r.json()
    #logger.info("scan_result: {}".format(json.dumps(scan_result, indent=2)))
    count = scan_result['hits']['total']
    scroll_id = scan_result['_scroll_id']
    hits = []
    while True:
        r = requests.post('%s/_search/scroll?scroll=60m' % rest_url, data=scroll_id)
        res = r.json()
        scroll_id = res['_scroll_id']
        if len(res['hits']['hits']) == 0: break
        hits.extend(res['hits']['hits'])
    return hits


def submit_acquisition_localizer_multi_job_rule(AOI_name, job_type, release, start_time, end_time, coordinates):
    with open('_context.json') as f:
      ctx = json.load(f)
    query_file = open(os.path.join(BASE_PATH, 'acquisition_localizer_multi_job_query.json'))
    query_temp = Template( query_file.read())
    query_str = query_temp.substitute({'start_time':'"'+start_time+'"','end_time':'"'+end_time+'"', 'coordinates':json.dumps(coordinates)})
    query_dict = json.loads(query_str)

    # rule submission for localizer for new acqs
    job_name = "acquisition_localizer_multi_{}".format(AOI_name)
    workflow_name = job_type+":"+release
    other_params = {'asf_ngap_download_queue':'spyddder-sling-extract-asf',
                  'esa_download_queue': 'factotum-job_worker-scihub_throttled',
                  'spyddder_sling_extract_version':ctx['SLC_spyddder_sling_extract_version']}
    priority = 7
    print("Going to add rule for {}".format(job_type))
    print("Rule names: {}".format(job_name))
    print("workflows: {}".format(workflow_name))
    print("priority: {}".format(str(priority)))
    print("rule: {}".format(query_str))
    print("other params: {}".format(other_params))
    add_user_rules.add_user_rule('factotum', job_name, workflow_name, priority, query_str, other_params)
    
    #get the acquisition list for 'products' based on the query for job_submission
    prod_query = {
        "query": query_dict,
        "partial_fields": {
            "partial": {
                "include": ["id"]
            }
        }
    }
    products = [i['fields']['partial'][0]['id']for i in query_es(prod_query)]
    other_params.update({'products':products})
    # job submission for localizer for exisiting acqs
    submit_jobs(job_name, job_type, release, other_params, query_str, job_name)



def submit_acq_submitter_job(AOI_name, coordinates, start_time, end_time, job_type, release):
    job_name = "acq_submitter_{}".format(AOI_name)
    job_params = {"AOI_name": AOI_name,
                  "spatial_extent":coordinates,
                  "start_time":start_time,
                  "end_time":end_time,
                  "dataset_version":'v2.0'}
    dataset_tag = "acq_submitter_{}".format(AOI_name)
    condition = {"query":{"bool": {"must": [{"term": {"dataset_type.raw": "area_of_interest"}},{"query_string": {"query": '_id:"AOI"',"default_operator": "OR"}}]}}}
    condition["query"]["bool"]["must"][1]["query_string"]["query"] = '_id:"'+AOI_name+'"'
    condition = json.dumps(condition)
    submit_jobs(job_name, job_type, release, job_params, condition, dataset_tag)


def rule_generation(open_ended, dataset_type, track_number, start_time, end_time, coordinates, passthrough):
    pass_obj = passthrough

    if 'bool' in pass_obj:
        subs_pass = pass_obj['bool']['must']
        pass_str = json.dumps(subs_pass)+','
    else:
        pass_str = ''

    if track_number:
        if "," in track_number:
            tracks = track_number.split(",")
            track_json = ''
            track_condition = '{"bool": {"should": ['
            for track in tracks:
                track_json +=  '{"term": {"metadata.trackNumber": "'+track.strip()+'"}},'
            track_condition += track_json[:-1]
            track_condition += "]}},"
        else:
            track_condition = '{"term": {"metadata.trackNumber": "'+track_number+'"}},'
    else:
        track_condition = ''

    if open_ended is False:
        if dataset_type == '"S1-COD"':
            file_rule = open(os.path.join(BASE_PATH, 'dpm_query.json'))
            rule_query_temp = Template( file_rule.read())
            rule_query = rule_query_temp.substitute({'dataset_type':dataset_type,'passthrough':pass_str, 'track_number':track_condition ,'start_time':'"'+start_time+'"','end_time':'"'+end_time+'"', 'coordinates':json.dumps(coordinates)})
        else:
            file_rule = open(os.path.join(BASE_PATH, 'ifg_query.json'))
            rule_query_temp = Template( file_rule.read())
            rule_query = rule_query_temp.substitute({'dataset_type':dataset_type,'passthrough':pass_str, 'track_number':track_condition ,'start_time':'"'+start_time+'"','end_time':'"'+end_time+'"', 'coordinates':json.dumps(coordinates)})
    else:
        file_rule = open(os.path.join(BASE_PATH, 'open_ended_query.json'))
        rule_query_temp = Template( file_rule.read())
        rule_query = rule_query_temp.substitute({'dataset_type':dataset_type,'passthrough':pass_str, 'track_number':track_condition ,'start_time':'"'+start_time+'"', 'coordinates':json.dumps(coordinates)})

    logger.debug("Rule generation query:\n {}".format(rule_query))
    print("Rule generation query:\n {}".format(rule_query))
    return rule_query

def co_event_rule(passthrough, dataset_type, track_number, event_time, coordinates):
    pass_obj = passthrough
    if 'bool' in pass_obj:
            subs_pass = pass_obj['bool']['must']
            pass_str = json.dumps(subs_pass)+','
    else:
            pass_str = ''

    if track_number:
        if "," in track_number:
            tracks = track_number.split(",")
            track_json = ''
            track_condition = '{"bool": {"should": ['
            for track in tracks:
                track_json +=  '{"term": {"metadata.trackNumber": "'+track.strip()+'"}},'
            track_condition += track_json[:-1]
            track_condition += "]}},"
        else:
            track_condition = '{"term": {"metadata.trackNumber": "'+track_number+'"}},'
    else:
        track_condition = ''

    co_seismic_rule = open(os.path.join(BASE_PATH, 'co_event_condition.json'))
    rule_temp = Template( co_seismic_rule.read())

    coordinates = str(coordinates).replace("u'","\"")
    coordinates = coordinates.replace("'","\"")

    co_seismic_query = rule_temp.substitute({'passthrough':pass_str, 'track_number':track_condition, 'dataset_type':'"'+dataset_type+'"' ,'event_time1':'"'+event_time+'"', 'event_time2':'"'+event_time+'"', 'coordinates':coordinates})
    print("co_seismic_query:\n")
    print(co_seismic_query)
    return co_seismic_query

def add_rule(mode, open_ended, AOI_name, coordinates, workflow, workflow_version, projectName, start_time, event_time, end_time, temporal_baseline, track_number, passthrough, minMatch, azimuth_looks, filter_strength, dem_type, range_looks, coverage_threshold, dataset_tag, overriding_azimuth_looks, overriding_range_looks, minmatch, min_overlap, include, exclude, event_name, dpmraw, dpm_v1, thr_cod, gamma, thr_alpha, band1, band4, yellow_to_red, blues, merge, rmburst, kml, kml_url, priority):
    # rules_info = ''
    workflow_name = workflow+":"+workflow_version
    #mode can be pre-event-, post-event-, event- or ''(in the case of monitoring)
    # open_ended would be boolean value

    if workflow.endswith("ifg"):
        rule_name = mode+'ifg_'+AOI_name
    elif workflow.endswith("slcp-mrpe"):
        rule_name = mode+'slcp_'+AOI_name
    elif workflow.endswith("lar"):
        rule_name = mode+'lar_'+AOI_name
    elif workflow.find("slcp2cod") != -1:
        rule_name = mode+'cod_'+AOI_name
    elif workflow.find("cod2dpm") != -1:
        rule_name = mode+'dpm_'+AOI_name

    logger.debug("Kicking off rules for response: {}".format(rule_name))
    print("Kicking off rules for response: {}".format(rule_name))

    if workflow.endswith("lar"):
        event_rule = rule_generation(open_ended, '"S1-SLCP"', track_number, start_time, end_time, coordinates, passthrough)
        other_params = {}
    elif workflow.endswith("ifg"):
        event_rule = rule_generation(open_ended, '"S1-IW_SLC"', track_number, start_time, end_time, coordinates, passthrough)
        other_params = {"dataset_tag":dataset_tag,"project":projectName , "singlesceneOnly": "true", "preReferencePairDirection": "backward", "postReferencePairDirection": "forward", "temporalBaseline":temporal_baseline,"minMatch":minMatch, "azimuth_looks":azimuth_looks, "filter_strength":filter_strength, "dem_type":dem_type, "range_looks":range_looks, "covth":coverage_threshold, "precise_orbit_only":"false"}
    elif workflow.endswith("slcp-mrpe"):
        event_rule = rule_generation(open_ended, '"S1-IW_SLC"', track_number, start_time, end_time, coordinates, passthrough)
        other_params = {"event_time":event_time, "start_time":start_time, "end_time":end_time, "dataset_tag":dataset_tag, "project":projectName, "singlesceneOnly": "true", "temporalBaseline":temporal_baseline, "minMatch":minMatch, "covth":coverage_threshold, "precise_orbit_only":"false", "azimuth_looks":azimuth_looks, "filter_strength":filter_strength, "dem_type":dem_type, "range_looks":range_looks}
    elif workflow.find("slcp2cod") != -1:
        event_rule = rule_generation(open_ended, '"S1-SLCP"', track_number, start_time, end_time, coordinates, passthrough)
        other_params = {"dataset_tag":dataset_tag, "project": projectName, "slcp_version":slcp_product_version, "aoi_name":AOI_name, "track_number": track_number, "overriding_azimuth_looks": overriding_azimuth_looks, "overriding_range_looks": overriding_range_looks, "minmatch": str(minmatch), "min_overlap": str(min_overlap)}
    elif workflow.find("cod2dpm") != -1:
        event_rule = rule_generation(open_ended, '"S1-COD"', track_number, start_time, end_time, coordinates, passthrough)
        other_params = {"include": include, "exclude": exclude, "event_name": AOI_name, "dpmraw": dpmraw, "dpm": dpm_v1, "thr_cod": thr_cod, "gamma": gamma, "thr_alpha": thr_alpha, "band1": band1, "band4": band4, "yellow_to_red": yellow_to_red, "blues": blues, "merge": merge, "rmburst": rmburst, "kml": kml, "kml_url": kml_url}

    logger.debug("Going to add {} rule for {}".format(mode,workflow))
    logger.debug("Rule names: {}".format(rule_name))
    logger.debug("workflows: {}".format(workflow_name))
    logger.debug("priority: {}".format(str(priority)))
    logger.debug("rule: {}".format(event_rule))
    logger.debug("other params: {}".format(other_params))

    print("Going to add {} rule for {}".format(mode,workflow))
    print("Rule names: {}".format(rule_name))
    print("workflows: {}".format(workflow_name))
    print("priority: {}".format(str(priority)))
    print("rule: {}".format(event_rule))
    print("other params: {}".format(other_params))

    # rules_info = "Added {} rule \n".format(mode)
    # "Rule name: {}\n".format(rule_name)
    # "workflow: {}\n".format(workflow_name)
    # "priority: {}\n".format(str(priority))
    #"event_rule: %s"% event_rule+"\n"
    #"other params: %s"% other_params+'\n'

    add_user_rules.add_user_rule(projectName, rule_name, workflow_name, priority, event_rule, other_params)
    logger.debug("{} rule added".format(mode))
    print("{} rule added".format(mode))

    if workflow.endswith("slcp-mrpe") or workflow.endswith("ifg"):
        # hardcoded components in slcp mrpe job with "from": "value" (see hysds.io.json.sciflo-s1-slcp-mrpe)
        other_params["auto_bbox"] = "true"
        other_params["preReferencePairDirection"] = "backward"
        other_params["postReferencePairDirection"] = "forward"
        other_params["name"] = name
        other_params["username"] = user_name

        #add on-demand job for S1-SLCs already in the system
        submit_jobs(rule_name, workflow, workflow_version, other_params, event_rule, dataset_tag)

    # return rules_info

def add_co_event_lar(event_rule, projectName, AOI_name, workflow, workflow_version, priority):
    #mode can be pre-event-, post-event- or ''(in the case of monitoring)

    other_params = {}
    mode = "co-event-"
    workflow_name = workflow+":"+workflow_version
    rule_name = mode+'lar_'+AOI_name
    print("Kicking off rules for response: {}".format(rule_name))
    print("Going to add {} rule for {}".format(mode,workflow))
    print("Rule names: {}".format(rule_name))
    print("workflows: {}".format(workflow_name))
    print("priority: {}".format(str(priority)))
    print("rule: {}".format(event_rule))
    print("other params: {}".format(other_params))

    add_user_rules.add_user_rule(projectName, rule_name, workflow_name, priority, event_rule, other_params)
    logger.debug("{} rule added".format(mode))
    print("{} rule added".format(mode))

def convert_datetime_for_slcp(date_time):
    time = parse(date_time)
    new_time = time.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
    return new_time

def mega_rules(AOI_name, coordinates, acq_rule, slc_rule, slcp_rule, lar_rule, ifg_rule, cod_rule, dpm_rule, acq_workflow, slc_workflow, slcp_workflow, lar_workflow, ifg_workflow, cod_workflow, dpm_workflow, acq_workflow_version, slc_workflow_version, slcp_workflow_version, lar_workflow_version, ifg_workflow_version, cod_workflow_version, dpm_workflow_version, projectName, start_time, end_time, event_time, temporal_baseline, track_number, passthrough, minMatch, range_looks, azimuth_looks, filter_strength, dem_type, coverage_threshold, dataset_tag, overriding_azimuth_looks, overriding_range_looks, minmatch, min_overlap, include, exclude, event_name, dpmraw, dpm_v1, thr_cod, gamma, thr_alpha, band1, band4, yellow_to_red, blues, merge, rmburst, kml, kml_url, emails):

    #check if event time exists
    if end_time != '':
        if event_time == '':
            # event_time doesn't exist
            # set trigger rules from starttime and endtime of AOI
            if ifg_rule:
                add_rule('', False, AOI_name, coordinates, ifg_workflow, ifg_workflow_version, projectName, start_time, "", end_time, temporal_baseline, track_number, passthrough, minMatch, azimuth_looks, filter_strength, dem_type, range_looks, coverage_threshold, dataset_tag, '', '', '', '', '', '', '', '','','', '', '', '', '', '', '', '', '', '', '', 4)
            if slcp_rule:
                start_time = convert_datetime_for_slcp(start_time)
                end_time = convert_datetime_for_slcp(end_time)
                if acq_rule:
                    # submit job to scrape acquisitions
                    submit_acq_submitter_job(AOI_name, coordinates, start_time, end_time, acq_workflow, acq_workflow_version)
                if slc_rule:
                    # submit job to scrape slcs based on AOI and acquisitons
                    submit_acquisition_localizer_multi_job_rule(AOI_name, slc_workflow, slc_workflow_version, start_time, end_time, coordinates)
                add_rule('', False, AOI_name, coordinates, slcp_workflow, slcp_workflow_version, projectName, start_time, "", end_time, temporal_baseline, track_number, passthrough, minMatch, azimuth_looks, filter_strength, dem_type, range_looks, coverage_threshold, dataset_tag, '', '', '', '', '', '', '', '', '','','', '', '', '', '', '', '', '', '', '', 4)
            if lar_rule:
                add_rule('', False, AOI_name, coordinates, lar_workflow, lar_workflow_version, projectName, start_time, "", end_time, temporal_baseline, track_number, passthrough, minMatch, azimuth_looks, filter_strength, dem_type, range_looks, '', dataset_tag, '', '', '', '', '', '', '', '', '', '', '','','', '', '', '', '', '', '', '', 4)
            if cod_rule:
                # if it's a not event the don't add cod rule
                print("COD rules are only added for events. So ignoreing COD_processing set to true flag.")
            if dpm_rule:
                # if it's a not event the don't add dpm rule
                print("DPM rules are only added for events. So ignoreing DPM_processing set to true flag.")
        else:
            # add pre-event, post-event and co-event trigger rules
            if ifg_rule:
                #add pre-event rule
                add_rule('pre-event-', False, AOI_name, coordinates, ifg_workflow, ifg_workflow_version, projectName, start_time, "", event_time, temporal_baseline, track_number, passthrough, minMatch, azimuth_looks, filter_strength, dem_type, range_looks, coverage_threshold, dataset_tag, '', '', '', '', '', '', '', '','','', '', '', '', '', '', '', '', '', '', '', 7)

                #add post-event rule
                add_rule('post-event-', False, AOI_name, coordinates, ifg_workflow, ifg_workflow_version, projectName, event_time, "", end_time, temporal_baseline, track_number, passthrough, minMatch, azimuth_looks, filter_strength, dem_type, range_looks, coverage_threshold, dataset_tag, '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', 7)
            if slcp_rule:
                start_time = convert_datetime_for_slcp(start_time)
                event_time = convert_datetime_for_slcp(event_time)
                end_time = convert_datetime_for_slcp(end_time)
                if acq_rule:
                    # submit job to scrape acquisitions
                    submit_acq_submitter_job(AOI_name, coordinates, start_time, end_time, acq_workflow, acq_workflow_version)
                if slc_rule:
                    # submit job to scrape slcs based on AOI and acquisitons
                    submit_acquisition_localizer_multi_job_rule(AOI_name, slc_workflow, slc_workflow_version, start_time, end_time, coordinates)
                add_rule('event-', False, AOI_name, coordinates, slcp_workflow, slcp_workflow_version, projectName, start_time, event_time, end_time, temporal_baseline, track_number, passthrough, minMatch, azimuth_looks, filter_strength, dem_type, range_looks, coverage_threshold, dataset_tag, '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', 7)
            if lar_rule:
                event_rule = co_event_rule(passthrough, "S1-SLCP", track_number, event_time, coordinates)
                add_co_event_lar(event_rule, projectName, AOI_name, lar_workflow, lar_workflow_version, 7)
            if cod_rule:
                # add event rule
                add_rule('event-', False, AOI_name, coordinates, cod_workflow, cod_workflow_version, projectName, start_time, "", end_time, temporal_baseline, track_number, passthrough, '', '', '', '', '', '', dataset_tag, overriding_azimuth_looks, overriding_range_looks, minmatch, min_overlap, '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', 7)
            if dpm_rule:
                # add event rule
                add_rule('event-', False, AOI_name, coordinates, dpm_workflow, dpm_workflow_version, projectName, start_time, "", end_time, temporal_baseline, track_number, passthrough, '', '', '', '', '', '', dataset_tag, '', '', '', '', include, exclude, event_name, dpmraw, dpm_v1, thr_cod, gamma, thr_alpha, band1, band4, yellow_to_red, blues, merge, rmburst, kml, kml_url, 7)
    else:
        logging.debug("Start time exists but no end time specified")
        if event_time == '':
            #only start time give
            logging.debug("Only start time available")
            if ifg_rule:
                add_rule('', True, AOI_name, coordinates, ifg_workflow, ifg_workflow_version, projectName, start_time, '', '', temporal_baseline, track_number, passthrough, minMatch, azimuth_looks, filter_strength, dem_type, range_looks, coverage_threshold, dataset_tag, '', '', '', '', '', '', '', '', '', '','','', '', '', '', '', '', '', '', '', 4)
            if slcp_rule:
                start_time = convert_datetime_for_slcp(start_time)
                if acq_rule:
                    # submit job to scrape acquisitions
                    submit_acq_submitter_job(AOI_name, coordinates, start_time, end_time, acq_workflow, acq_workflow_version)
                if slc_rule:
                    # submit job to scrape slcs based on AOI and acquisitons
                    submit_acquisition_localizer_multi_job_rule(AOI_name, slc_workflow, slc_workflow_version, start_time, end_time, coordinates)
                add_rule('', True, AOI_name, coordinates, slcp_workflow, slcp_workflow_version, projectName, start_time, '', '', temporal_baseline, track_number, passthrough, minMatch, azimuth_looks, filter_strength, dem_type, range_looks, coverage_threshold, dataset_tag, '', '', '', '', '', '', '', '', '', '', '', '','', '', '', '', '', '', '', '', 4)
            if lar_rule:
                add_rule('', True, AOI_name, coordinates, lar_workflow, lar_workflow_version, projectName, start_time, '', '', temporal_baseline, track_number, passthrough, minMatch, azimuth_looks, filter_strength, dem_type, range_looks, "", dataset_tag, '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', 4)
            if cod_rule:
                #not adding COD because this is not an event
                print("COD rules are only added for events. So ignoreing COD_processing set to true flag.")
            if dpm_rule:
                #not adding DPM because this is not an event
                print("DPM rules are only added for events. So ignoreing DPM_processing set to true flag.")
        else:
            #start time and event time given
            logging.debug("Need to add a pre-event and post event needs to be added")
            if ifg_rule:
                #add pre-event rule
                add_rule('pre-event-', False, AOI_name, coordinates, ifg_workflow, ifg_workflow_version, projectName, start_time, '', event_time, temporal_baseline, track_number, passthrough, minMatch, azimuth_looks, filter_strength, dem_type, range_looks, coverage_threshold, dataset_tag, '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', 7)
                #add post-event rule
                add_rule('post-event-', True, AOI_name, coordinates, ifg_workflow, ifg_workflow_version, projectName, event_time, '', '', temporal_baseline, track_number, passthrough, minMatch, azimuth_looks, filter_strength, dem_type, range_looks, coverage_threshold, dataset_tag, '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', 7)

            if slcp_rule:
                start_time = convert_datetime_for_slcp(start_time)
                event_time = convert_datetime_for_slcp(event_time)
                if acq_rule:
                    # submit job to scrape acquisitions
                    submit_acq_submitter_job(AOI_name, coordinates, start_time, end_time, acq_workflow, acq_workflow_version)
                if slc_rule:
                    # submit job to scrape slcs based on AOI and acquisitons
                    submit_acquisition_localizer_multi_job_rule(AOI_name, slc_workflow, slc_workflow_version, start_time, end_time, coordinates)
                add_rule('pre-event-', False, AOI_name, coordinates, slcp_workflow, slcp_workflow_version, projectName, start_time, '', event_time, temporal_baseline, track_number, passthrough, minMatch, azimuth_looks, filter_strength, dem_type, range_looks, coverage_threshold, dataset_tag, '', '', '', '', '', '', '', '', '', '','', '', '', '', '', '', '', '', '', '', 7)
                add_rule('post-event-', True, AOI_name, coordinates, slcp_workflow, slcp_workflow_version, projectName, event_time, '', '', temporal_baseline, track_number, passthrough, minMatch, azimuth_looks, filter_strength, dem_type, range_looks, coverage_threshold, dataset_tag, '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', 7)

            if lar_rule:
                co_event_rule(passthrough, "S1-LAR", track_number, event_time, coordinates)
            if cod_rule:
                add_rule('event-', False, AOI_name, coordinates, cod_workflow, cod_workflow_version, projectName, start_time, '', '', temporal_baseline, track_number, passthrough, '', '', '', '', '', '', dataset_tag, overriding_azimuth_looks, overriding_range_looks, minmatch, min_overlap, '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', 7)
            if dpm_rule:
                add_rule('event-', False, AOI_name, coordinates, dpm_workflow, dpm_workflow_version, projectName, start_time, '', '', temporal_baseline, track_number, passthrough, '', '', '', '', '', '', dataset_tag, '', '', '', '', include, exclude, event_name, dpmraw, dpm_v1, thr_cod, gamma, thr_alpha, band1, band4, yellow_to_red, blues, merge, rmburst, kml, kml_url, 7)


if __name__ == "__main__":
    '''
    Main program of purge_products
    '''
    with open('_context.json') as f:
      ctx = json.load(f)

    # now let's add user rules
    # workflow is the name of the hysds-io tosca action and version number, needs to be inputted by the operator
    user_name = ctx['username']
    name = ctx['name']
    AOI_name = ctx['AOI_name']
    projectName = ctx['project_name']
    starttime = ''
    endtime = ''
    eventtime = ''

    acq = ctx['acquisitions_scraper_processing']
    slc = ctx['SLC_processing']
    ifg = ctx['IFG_processing']
    slcp = ctx['SLCP_processing']
    lar = ctx['LAR_processing']
    cod = ctx['COD_processing']
    dpm = ctx['DPM_processing']

    acq_workflow = ctx['acquisitions_scraper_workflow']
    slc_workflow = ctx['slc_workflow']
    ifg_workflow = ctx['ifg_workflow']
    slcp_workflow= ctx['slcp_workflow']
    lar_workflow = ctx['lar_workflow']
    cod_workflow = ctx['cod_workflow']
    dpm_workflow = ctx['dpm_workflow']

    acq_version = ctx['acquisitions_scraper_workflow_version']
    slc_version = ctx['SLC_workflow_version']
    ifg_version = ctx['IFG_workflow_version']
    slcp_version = ctx['SLCP_workflow_version']
    lar_version = ctx['LAR_workflow_version']
    cod_version = ctx['COD_workflow_version']
    dpm_version = ctx['DPM_workflow_version']

    azimuth_looks = ctx['azimuth_looks']
    range_looks = ctx['range_looks']
    filter_strength = ctx["filter_strength"]
    dem_type = ctx["dem_type"]
    emails = "" # disabled emails
    passthrough = ctx['query']
    coverage_threshold = ctx['coverage_threshold']
    dataset_tag = ctx['dataset_tag']
    track_number = ctx['track_number']
    temporal_baseline = ctx['temporal_baseline']
    minMatch = ctx['minimum_pair']

    # parameters for slcp2cod
    overriding_azimuth_looks = ctx['overriding_azimuth_looks']
    overriding_range_looks = ctx['overriding_range_looks']
    minmatch = ctx['minmatch']
    min_overlap = ctx['min_overlap']

    #parameters for cod2dpm
    include = ctx['include']
    exclude = ctx['exclude']
    event_name = ctx['event_name']
    dpmraw = ctx['dpmraw']
    dpm_v1 = ctx['dpm']
    thr_cod = ctx['thr_cod']
    gamma = ctx['gamma']
    thr_alpha = ctx['thr_alpha']
    band1 = ctx['band1']
    band4 = ctx['band4']
    yellow_to_red = ctx['yellow_to_red']
    blues = ctx['blues']
    merge = ctx['merge']
    rmburst = ctx['rmburst']
    kml = ctx['kml']
    kml_url = ctx['kml_url']

    r = get_AOI(AOI_name)
    if r.status_code != 200:
        print("Failed to query ES. Got status code %d:\n%s" %(r.status_code, json.dumps(r.json(), indent=2)))
        logger.debug("Failed to query ES. Got status code %d:\n%s" % (r.status_code, json.dumps(r.json(), indent=2)))
        r.raise_for_status()
        logger.debug("result: %s" % r.json())

        # check if AOI has event_time specified.
        # mine out the start, end and event time.
    result = r.json()
    coordinates = result["hits"]["hits"][0]["_source"]["location"]
    starttime = result["hits"]["hits"][0]["_source"]["starttime"]
    if 'endtime' not in result["hits"]["hits"][0]["_source"]:
        logger.info("AOI doesn't have associated endtime")
    else:
        endtime = result["hits"]["hits"][0]["_source"]["endtime"]

    if 'eventtime' not in result["hits"]["hits"][0]["_source"]["metadata"]:
        logger.info("AOI doesn't have associated eventtime")
    else:
        eventtime = result["hits"]["hits"][0]["_source"]["metadata"]["eventtime"]

    mega_rules(AOI_name, coordinates, acq, slc, slcp, lar, ifg, cod, dpm, acq_workflow, slc_workflow, slcp_workflow, lar_workflow, ifg_workflow, cod_workflow, dpm_workflow, acq_version, slc_version, slcp_version, lar_version, ifg_version, cod_version, dpm_version, projectName, starttime, endtime, eventtime, temporal_baseline, track_number, passthrough, minMatch, range_looks, azimuth_looks, filter_strength, dem_type, coverage_threshold, dataset_tag, overriding_azimuth_looks, overriding_range_looks, minmatch, min_overlap, include, exclude, event_name, dpmraw, dpm_v1, thr_cod, gamma, thr_alpha, band1, band4, yellow_to_red, blues, merge, rmburst, kml, kml_url, emails)
