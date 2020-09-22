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

def email_to_user(emails, project_name, rule_names, rules_info):
    logger.debug("New rule(s) triggered. \nNeed to send email to admin")
    print ("New rule(s) triggered. \nNeed to send email to admin")
    attachments = None
    if emails != '':
       to_recipients = [i.strip() for i in emails.split(',')]
    else:
       to_recipients = ''

    bcc_recipients = ''
    subject = "[Rule Added] (%s)" % (project_name)

    body = "Hi,\n"
    body += "New trigger rules have been added using the 'Add trigger rules' action. To see the parameters and conditions for each rule created, please check 'My Rules' in the Aria Search interface.\n"
    body += "\nFor project: "+project_name+"\n"
    body += "Rule names: "+",".join([str(i) for i in rule_names])+"\n"
    body += rules_info
    body += "If you have any questions, please email aria-help@jpl.nasa.gov\n"
    body += "Thanks,\n Aria"
    notify_by_email.send_email("noreply-hysds@jpl.nasa.gov", to_recipients, bcc_recipients, subject, body, attachments=attachments)
    logger.info("Email sent to %s",emails)
    print ("Email sent to {}".format(emails))

def submit_jobs(job_name, job_type, release, job_params, condition, dataset_tag):
    # submit mozart job
    MOZART_URL = app.conf['MOZART_URL']
    job_submit_url = '%s/mozart/api/v0.1/job/submit' % MOZART_URL

    job_params["query"] = {"query": json.loads(condition)}
    job = job_type[job_type.find("hysds-io-")+9:]
    params = {}
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
        if result['success'] == True:
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

def submit_acquisition_localizer_multi_job(AOI_name, job_type, release, start_time, end_time, coordinates):
    query_file = open(os.path.join(BASE_PATH, 'acquisition_localizer_multi_job_query.json'))
    query_temp = Template( query_file.read())
    condition = query_temp.substitute({'start_time':'"'+start_time+'"','end_time':'"'+end_time+'"', 'coordinates':json.dumps(coordinates)})
    job_name = "acquisition_localizer_multi_{}".format(AOI_name)
    job_params = {}
    dataset_tag = "acquisition_localizer_multi_{}".format(AOI_name)
    submit_jobs(job_name, job_type, release, job_params, json.dumps(condition), dataset_tag)

def submit_acq_submitter_job(AOI_name, job_type, release):
    job_name = "acq_submitter_{}".format(AOI_name)
    job_params = {}
    dataset_tag = "acq_submitter_{}".format(AOI_name)
    condition = {"query":{"bool": {"must": [{"term": {"dataset_type.raw": "area_of_interest"}},{"query_string": {"query": '_id:"AOI"',"default_operator": "OR"}}]}}}
    condition["query"]["bool"]["must"][1]["query_string"]["query"] = '_id:"'+AOI_name+'"'
    submit_jobs(job_name, job_type, release, job_params, json.dumps(condition), dataset_tag)


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

def add_rule(mode, open_ended, AOI_name, coordinates, workflow, workflow_version, projectName, start_time, event_time, end_time, temporal_baseline, track_number, passthrough, minMatch, azimuth_looks, filter_strength, dem_type, range_looks, coverage_threshold, dataset_tag, overriding_azimuth_looks, overriding_range_looks, minmatch, min_overlap, include, exclude, event_name, thr_cod, gamma, thr_alpha, band1, band4, yellow_to_red, blues, merge, rmburst, kml, kml_url, priority):
    rules_info = ''
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
        acq_scraper_job_query = rule_generation(open_ended, '"area_of_interest"', track_number, start_time, end_time, coordinates, passthrough)
    elif workflow.find("slcp2cod") != -1:
        event_rule = rule_generation(open_ended, '"S1-SLCP"', track_number, start_time, end_time, coordinates, passthrough)
        other_params = {"dataset_tag":dataset_tag, "project": projectName, "slcp_version":slcp_product_version, "aoi_name":AOI_name, "track_number": track_number, "overriding_azimuth_looks": overriding_azimuth_looks, "overriding_range_looks": overriding_range_looks, "minmatch": minmatch, "min_overlap": min_overlap}
    elif workflow.find("cod2dpm") != -1:
        event_rule = rule_generation(open_ended, '"S1-COD"', track_number, start_time, end_time, coordinates, passthrough)
        other_params = {"include": include, "exclude": exclude, "event_name": AOI_name, "thr_cod": thr_cod, "gamma": gamma, "thr_alpha": thr_alpha, "band1": band1, "band4": band4, "yellow_to_red": yellow_to_red, "blues": blues, "merge": merge, "rmburst": rmburst, "kml": kml, "kml_url": kml_url}

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

    rules_info = "Added {} rule \n".format(mode)
    rules_info += "Rule name: {}\n".format(rule_name)
    rules_info += "workflow: {}\n".format(workflow_name)
    rules_info += "priority: {}\n".format(str(priority))
    #rules_info += "event_rule: %s"% event_rule+"\n"
    #rules_info += "other params: %s"% other_params+'\n'

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

    return rules_info

def add_co_event_lar(event_rule, projectName, AOI_name, workflow, workflow_version, priority):
    #mode can be pre-event-, post-event- or ''(in the case of monitoring)

    other_params = {}
    mode = "co-event-"
    workflow_name = workflow+":"+workflow_version
    rule_name = mode+'lar_'+AOI_name

    logger.debug("Kicking off rules for response: {}".format(rule_name))
    print("Kicking off rules for response: {}".format(rule_name))

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

    rules_info = "Added {} rule \n".format(mode)
    rules_info += "Rule name: {}\n".format(rule_name)
    rules_info += "workflow: {}\n".format(workflow_name)
    rules_info += "priority: {}\n".format(str(priority))
    #rules_info += "event_rule: %s"% event_rule+"\n"
    #rules_info += "other params: %s"% other_params+'\n'

    add_user_rules.add_user_rule(projectName, rule_name, workflow_name, priority, event_rule, other_params)
    logger.debug("{} rule added".format(mode))
    print("{} rule added".format(mode))

    return rules_info


def add_email_rule(AOI_name, dataset, track_number, passthrough, event_time, coordinates, emails):

    if dataset == "S1-SLCP":
        product_type = "slcp"
    elif dataset == "S1-IFG":
        product_type = "ifg"
    elif dataset == "S1-LAR":
        product_type = "lar"
    elif dataset == "S1-COD":
        product_type = "cod"
    elif dataset == "S1-DPM":
        product_type = "dpm"

    email_rule_set = co_event_rule(passthrough, dataset, track_number, event_time, json.dumps(coordinates))
    other_params = {"emails": emails}

    logger.debug("Going to add email notification rule for co-seismic products")
    logger.debug("Rule name: %s", AOI_name+"-"+product_type+"_email")
    logger.debug("workflow: %s", notify_by_email_io+":"+email_job_version)
    logger.debug("priority: %s", '0')
    logger.debug("email_rule_set: %s",email_rule_set)
    logger.debug("other params: %s", other_params)
    logger.debug("Event notification rule added")

    rules_info = "Added email notification rule for co-seismic products\n"
    rules_info += "Rule name: %s"%AOI_name+"-"+product_type+"_email"+'\n'
    rules_info += "workflow: %s"% notify_by_email_io+":"+email_job_version+'\n'
    rules_info += "priority: %s"% '0\n'
    rules_info += "email notification rule: %s"%email_rule_set+"\n"
    rules_info +="other params: %s"%other_params+'\n'

    print("Going to add email notification rule for co-seismic products")
    print("Rule name: %s", AOI_name+"-"+product_type+"_email")
    print("workflow: %s", notify_by_email_io+":"+email_job_version)
    print("priority: %s", '0')
    print("email_rule_set: %s",email_rule_set)
    print("other params: %s", other_params)
    add_user_rules.add_user_rule(projectName, AOI_name+"-"+product_type+"_email", notify_by_email_io+":"+email_job_version, 0, email_rule_set, other_params)
    logger.debug("Event notification rule added")
    print("Event notification rule added")
        
    return rules_info

def convert_datetime_for_slcp(date_time):
    time = parse(date_time)
    new_time = time.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
    return new_time

def mega_rules(AOI_name, coordinates, acq_rule, slc_rule, slcp_rule, lar_rule, ifg_rule, cod_rule, dpm_rule, acq_workflow, slc_workflow, slcp_workflow, lar_workflow, ifg_workflow, cod_workflow, dpm_workflow, acq_workflow_version, slc_workflow_version, slcp_workflow_version, lar_workflow_version, ifg_workflow_version, cod_workflow_version, dpm_workflow_version, projectName, start_time, end_time, event_time, temporal_baseline, track_number, passthrough, minMatch, range_looks, azimuth_looks, filter_strength, dem_type, coverage_threshold, dataset_tag, overriding_azimuth_looks, overriding_range_looks, minmatch, min_overlap, include, exclude, event_name, thr_cod, gamma, thr_alpha, band1, band4, yellow_to_red, blues, merge, rmburst, kml, kml_url, emails):

    rule_names = []
    rules_info = ''
    #check if event time exists
    if end_time != '':
        if event_time == '':
            # event_time doesn't exist
            # set trigger rules from starttime and endtime of AOI
            if ifg_rule == True:
                rules_info += add_rule('', False, AOI_name, coordinates, ifg_workflow, ifg_workflow_version, projectName, start_time, "", end_time, temporal_baseline, track_number, passthrough, minMatch, azimuth_looks, filter_strength, dem_type, range_looks, coverage_threshold, dataset_tag, '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', 4)
                rule_names.extend(['ifg_'+AOI_name])
            if slcp_rule == True:
                start_time = convert_datetime_for_slcp(start_time)
                end_time = convert_datetime_for_slcp(end_time)
                if acq_rule == True:
                    # submit job to scrape acquisitions
                    submit_acq_submitter_job(AOI_name, acq_workflow, acq_workflow_version)
                if slc_rule == True:
                    # submit job to scrape slcs based on AOI and acquisitons
                    submit_acquisition_localizer_multi_job(AOI_name, slc_workflow, slc_workflow_version, start_time, end_time, coordinates)
                rules_info += add_rule('', False, AOI_name, coordinates, slcp_workflow, slcp_workflow_version, projectName, start_time, "", end_time, temporal_baseline, track_number, passthrough, minMatch, azimuth_looks, filter_strength, dem_type, range_looks, coverage_threshold, dataset_tag, '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', 4)
                rule_names.extend(['slcp_'+AOI_name])
            if lar_rule == True:
                rules_info += add_rule('', False, AOI_name, coordinates, lar_workflow, lar_workflow_version, projectName, start_time, "", end_time, temporal_baseline, track_number, passthrough, minMatch, azimuth_looks, filter_strength, dem_type, range_looks, '', dataset_tag, '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', 4)
                rule_names.extend(['lar_'+AOI_name])
            if cod_rule == True:
                # if it's a not event the don't add cod rule
                print("COD rules are only added for events. So ignoreing COD_processing set to true flag.")
                #rules_info += add_rule('', False, AOI_name, coordinates, cod_workflow, cod_workflow_version, projectName, start_time, "", end_time, temporal_baseline, track_number, passthrough, '', '', '', '', '', 4)
            if dpm_rule == True:
                # if it's a not event the don't add dpm rule
                print("DPM rules are only added for events. So ignoreing DPM_processing set to true flag.")
        else:
            # add pre-event, post-event and co-event trigger rules
            if ifg_rule == True:
                #add pre-event rule
                rules_info += add_rule('pre-event-', False, AOI_name, coordinates, ifg_workflow, ifg_workflow_version, projectName, start_time, "", event_time, temporal_baseline, track_number, passthrough, minMatch, azimuth_looks, filter_strength, dem_type, range_looks, coverage_threshold, dataset_tag, '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', 7)

                #add post-event rule
                rules_info += add_rule('post-event-', False, AOI_name, coordinates, ifg_workflow, ifg_workflow_version, projectName, event_time, "", end_time, temporal_baseline, track_number, passthrough, minMatch, azimuth_looks, filter_strength, dem_type, range_looks, coverage_threshold, dataset_tag, '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', 7)
                rule_names.extend(['pre-event-ifg_'+AOI_name, "post-event-ifg_"+AOI_name])
                #add mail rule
                rules_info += add_email_rule(AOI_name, "S1-IFG", track_number, passthrough, event_time, coordinates, emails)
                rule_names.extend([AOI_name+"-ifg_email"])
            if slcp_rule == True:
                start_time = convert_datetime_for_slcp(start_time)
                event_time = convert_datetime_for_slcp(event_time)
                end_time = convert_datetime_for_slcp(end_time)
                if acq_rule == True:
                    # submit job to scrape acquisitions
                    submit_acq_submitter_job(AOI_name, acq_workflow, acq_workflow_version)
                if slc_rule == True:
                    # submit job to scrape slcs based on AOI and acquisitons
                    submit_acquisition_localizer_multi_job(AOI_name, slc_workflow, slc_workflow_version, start_time, end_time, coordinates)
                rules_info += add_rule('event-', False, AOI_name, coordinates, slcp_workflow, slcp_workflow_version, projectName, start_time, event_time, end_time, temporal_baseline, track_number, passthrough, minMatch, azimuth_looks, filter_strength, dem_type, range_looks, coverage_threshold, dataset_tag, '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', 7)
                rule_names.extend(["event-slcp_"+AOI_name, "post-event-slcp_"+AOI_name])
                #add email rule
                rules_info += add_email_rule(AOI_name, "S1-SLCP", track_number, passthrough, event_time, coordinates, emails)
                rule_names.extend([AOI_name+"-slcp_email"])
            if lar_rule == True:
                event_rule = co_event_rule(passthrough, "S1-SLCP", track_number, event_time, coordinates)
                rules_info += add_co_event_lar(event_rule, projectName, AOI_name, lar_workflow, lar_workflow_version, 7)
                rule_names.extend(["co-event-lar_"+AOI_name])
                #add email rule
                rules_info += add_email_rule(AOI_name, "S1-LAR", track_number, passthrough, event_time, coordinates, emails)
                rule_names.extend([AOI_name+"-lar_email"])
            if cod_rule == True:
                # add event rule
                rules_info += add_rule('event-', False, AOI_name, coordinates, cod_workflow, cod_workflow_version, projectName, start_time, "", end_time, temporal_baseline, track_number, passthrough, '', '', '', '', '', '', dataset_tag, overriding_azimuth_looks, overriding_range_looks, minmatch, min_overlap, '', '', '', '', '', '', '', '', '', '', '', '', '', '', 7)
                rule_names.extend(['event-cod_'+AOI_name])
                #add mail rule
                rules_info += add_email_rule(AOI_name, "S1-COD", track_number, passthrough, event_time, coordinates, emails)
                rule_names.extend([AOI_name+"-cod_email"])
            if dpm_rule == True:
                # add event rule
                rules_info += add_rule('event-', False, AOI_name, coordinates, dpm_workflow, dpm_workflow_version, projectName, start_time, "", end_time, temporal_baseline, track_number, passthrough, '', '', '', '', '', '', dataset_tag, '', '', '', '', include, exclude, event_name, thr_cod, gamma, thr_alpha, band1, band4, yellow_to_red, blues, merge, rmburst, kml, kml_url, 7)
                rule_names.extend(['event-dpm_'+AOI_name])
                #add mail rule
                rules_info += add_email_rule(AOI_name, "S1-DPM", track_number, passthrough, event_time, coordinates, emails)
                rule_names.extend([AOI_name+"-dpm_email"])
    else:
        logging.debug("Start time exists but no end time specified")
        if event_time == '':
            #only start time give
            logging.debug("Only start time available")
            if ifg_rule:
                rules_info += add_rule('', True, AOI_name, coordinates, ifg_workflow, ifg_workflow_version, projectName, start_time, '', '', temporal_baseline, track_number, passthrough, minMatch, azimuth_looks, filter_strength, dem_type, range_looks, coverage_threshold, dataset_tag, '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', 4)
                rule_names.extend(['ifg_'+AOI_name])
            if slcp_rule:
                start_time = convert_datetime_for_slcp(start_time)
                if acq_rule == True:
                    # submit job to scrape acquisitions
                    submit_acq_submitter_job(AOI_name, acq_workflow, acq_workflow_version)
                if slc_rule == True:
                    # submit job to scrape slcs based on AOI and acquisitons
                    submit_acquisition_localizer_multi_job(AOI_name, slc_workflow, slc_workflow_version, start_time, end_time, coordinates)
                rules_info += add_rule('', True, AOI_name, coordinates, slcp_workflow, slcp_workflow_version, projectName, start_time, '', '', temporal_baseline, track_number, passthrough, minMatch, azimuth_looks, filter_strength, dem_type, range_looks, coverage_threshold, dataset_tag, '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', 4)
                rule_names.extend(['slcp_'+AOI_name])
            if lar_rule:
                rules_info += add_rule('', True, AOI_name, coordinates, lar_workflow, lar_workflow_version, projectName, start_time, '', '', temporal_baseline, track_number, passthrough, minMatch, azimuth_looks, filter_strength, dem_type, range_looks, "", dataset_tag, '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', 4)
                rule_names.extend(['lar_'+AOI_name])
            if cod_rule:
                #not adding COD because this is not an event
                print("COD rules are only added for events. So ignoreing COD_processing set to true flag.")
                #rule_names.extend(['cod_'+AOI_name])
            if dpm_rule:
                #not adding DPM because this is not an event
                print("DPM rules are only added for events. So ignoreing DPM_processing set to true flag.")
                #rule_names.extend(['dpm_'+AOI_name])
        else:
            #start time and event time given
            logging.debug("Need to add a pre-event and post event needs to be added")
            if ifg_rule == True:
                #add pre-event rule
                rules_info += add_rule('pre-event-', False, AOI_name, coordinates, ifg_workflow, ifg_workflow_version, projectName, start_time, '', event_time, temporal_baseline, track_number, passthrough, minMatch, azimuth_looks, filter_strength, dem_type, range_looks, coverage_threshold, dataset_tag, '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', 7)
                #add post-event rule
                rules_info += add_rule('post-event-', True, AOI_name, coordinates, ifg_workflow, ifg_workflow_version, projectName, event_time, '', '', temporal_baseline, track_number, passthrough, minMatch, azimuth_looks, filter_strength, dem_type, range_looks, coverage_threshold, dataset_tag, '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', 7)
                rule_names.extend(['pre-event-ifg_'+AOI_name, "post-event-ifg_"+AOI_name])
                #add mail rule
                rules_info += add_email_rule(AOI_name, "S1-IFG", track_number, passthrough, event_time, coordinates, emails)
                rule_names.extend([AOI_name+"-ifg_email"])

            if slcp_rule == True:
                start_time = convert_datetime_for_slcp(start_time)
                event_time = convert_datetime_for_slcp(event_time)
                if acq_rule == True:
                    # submit job to scrape acquisitions
                    submit_acq_submitter_job(AOI_name, acq_workflow, acq_workflow_version)
                if slc_rule == True:
                    # submit job to scrape slcs based on AOI and acquisitons
                    submit_acquisition_localizer_multi_job(AOI_name, slc_workflow, slc_workflow_version, start_time, end_time, coordinates)
                rules_info += add_rule('pre-event-', False, AOI_name, coordinates, slcp_workflow, slcp_workflow_version, projectName, start_time, '', event_time, temporal_baseline, track_number, passthrough, minMatch, azimuth_looks, filter_strength, dem_type, range_looks, coverage_threshold, dataset_tag, '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', 7)

                rules_info += add_rule('post-event-', True, AOI_name, coordinates, slcp_workflow, slcp_workflow_version, projectName, event_time, '', '', temporal_baseline, track_number, passthrough, minMatch, azimuth_looks, filter_strength, dem_type, range_looks, coverage_threshold, dataset_tag, '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', 7)
                rule_names.extend(["pre-event-slcp_"+AOI_name, "post-event-slcp_"+AOI_name])
                #add email rule
                rules_info += add_email_rule(AOI_name, "S1-SLCP", track_number, passthrough, event_time, coordinates, emails)
                rule_names.extend([AOI_name+"-slcp_email"])

            if lar_rule == True:
                rules_info += co_event_rule(passthrough, "S1-LAR", track_number, event_time, coordinates)
                rule_names.extend(["co-event-lar_"+AOI_name])
                #add email rule
                rules_info += add_email_rule(AOI_name, "S1-LAR", track_number, passthrough, event_time, coordinates, emails)
                rule_names.extend([AOI_name+"-lar_email"])

            if cod_rule == True:
                rules_info += add_rule('event-', False, AOI_name, coordinates, cod_workflow, cod_workflow_version, projectName, start_time, '', '', temporal_baseline, track_number, passthrough, '', '', '', '', '', '', dataset_tag, overriding_azimuth_looks, overriding_range_looks, minmatch, min_overlap, '', '', '', '', '', '', '', '', '', '', '', '', '', '', 7)
                rule_names.extend(["event-cod_"+AOI_name])
                #add email rule
                rules_info += add_email_rule(AOI_name, "S1-COD", track_number, passthrough, event_time, coordinates, emails)
                rule_names.extend([AOI_name+"-cod_email"])

            if dpm_rule == True:
                rules_info += add_rule('event-', False, AOI_name, coordinates, dpm_workflow, dpm_workflow_version, projectName, start_time, '', '', temporal_baseline, track_number, passthrough, '', '', '', '', '', '', dataset_tag, '', '', '', '', include, exclude, event_name, thr_cod, gamma, thr_alpha, band1, band4, yellow_to_red, blues, merge, rmburst, kml, kml_url, 7)
                rule_names.extend(["event-dpm_"+AOI_name])
                #add email rule
                rules_info += add_email_rule(AOI_name, "S1-DPM", track_number, passthrough, event_time, coordinates, emails)
                rule_names.extend([AOI_name+"-dpm_email"])

    #send out email to admin
    # logger.debug("Sending email to admin with details of rules created")
    # print("Sending email to admin with details of rules created")

    # if emails != '':
    #     email_to_user(emails, projectName, rule_names, rules_info)
    #     logger.debug("Email sent to admin")
    #     print("Email sent to admin")

    #end of mega_rules

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

    mega_rules(AOI_name, coordinates, acq, slc, slcp, lar, ifg, cod, dpm, acq_workflow, slc_workflow, slcp_workflow, lar_workflow, ifg_workflow, cod_workflow, dpm_workflow, acq_version, slc_version, slcp_version, lar_version, ifg_version, cod_version, dpm_version, projectName, starttime, endtime, eventtime, temporal_baseline, track_number, passthrough, minMatch, range_looks, azimuth_looks, filter_strength, dem_type, coverage_threshold, dataset_tag, overriding_azimuth_looks, overriding_range_looks, minmatch, min_overlap, include, exclude, event_name, thr_cod, gamma, thr_alpha, band1, band4, yellow_to_red, blues, merge, rmburst, kml, kml_url, emails)
