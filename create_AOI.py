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

#Setup logger for this job here.  Should log to STDOUT or STDERR as this is a job
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("hysds")

#manually update this block when there is unsync with avaliable version of email and slcp product version
notify_by_email_io = "hysds-io-lw-tosca-notify-by-email"
email_job_version = "release-20170510"
admin_email = "grfn-ops@jpl.nasa.gov"
slcp_product_version = "v1.1.3" #look at ariamh/conf/dataset_versions.json under the correct release version
user_name = None
name = None
BASE_PATH = os.path.dirname(__file__)

def email_to_user(AOI_name, emails, use_case, project_name, rule_names, rules_info):
    logger.debug("New rule(s) triggered. \nNeed to send email to admin")
    print ("New rule(s) triggered. \nNeed to send email to admin")
    attachments = None
    body = ''
    if emails != '':
       to_recipients = [i.strip() for i in emails.split(',')]
    else:
       to_recipients = ''
    bcc_recipients = ''
    subject = "[Rule Added] (%s : %s)" % (use_case,project_name)
    if use_case == "no_rules":
	body = rules_info
	body += "\nFor project: "+project_name+"\n"
    elif use_case == "mega":
	body = "Hi,\n"
	body += "New trigger rules have been added using the 'Add trigger rules' action. To see the parameters and conditions for each rule created, please check 'My Rules' in the Aria Search interface.\n"
    	body += "\nFor project: "+project_name+"\n"
   	body += "Rule names: "+",".join([str(i) for i in rule_names])+"\n"
    	body += rules_info

    body += "If you have any questions, please email aria-help@jpl.nasa.gov\n"
    body += "Thanks,\n Aria"
    
    if use_case == 'no_rules':
    	if os.path.isfile(AOI_name+'/'+AOI_name+'.met.json'):
		print AOI_name
		met_file = AOI_name+'/'+AOI_name+'.met.json'
        	met_content = open(met_file,'r').read()
    	if os.path.isfile(AOI_name+'/'+AOI_name+'.dataset.json'):
		dataset_file = AOI_name+'/'+AOI_name+'.dataset.json'
		datasets_content = open(dataset_file,'r').read()
    
    	attachments = { AOI_name+'.met.json':met_content , AOI_name+'.dataset.json':datasets_content}

    notify_by_email.send_email("noreply-hysds@jpl.nasa.gov", to_recipients, bcc_recipients, subject, body, attachments=attachments)
    logger.info("Email sent to %s",emails)
    print ("Email sent to %s",emails)

def submit_jobs(job_name, job_type, release, job_params, condition, dataset_tag):
    # submit mozart job
    MOZART_URL = app.conf['MOZART_URL']
    job_submit_url = '%s/mozart/api/v0.1/job/submit' % MOZART_URL

    '''
    name:test_notify_aria_hostname
    workflow:hysds-io-lw-tosca-notify-by-email:release-20180130
    queue:system-jobs-queue
    priority:6
    query_string:{
      "bool": {
        "must": [
          {
            "term": {
            "dataset.raw": "S1-IW_SLC"
        }
      },
      {
        "term": {
          "metadata.user_tags.raw": "test_offset"
            }
           }
        ]
      }
    }
    kwargs:{
     "emails": "namrata.malarout@jpl.nasa.gov"
    }
    '''
    job_params["query"] = json.loads(condition)
    job = job_type[job_type.find("hysds-io-")+9:]
    '''params = {
        'queue': 'aria-job_worker-small',
        'priority': '5',
        'name': job_name,
        'tags': ["%s" % dataset_tag],
        'type': 'job-%s:%s' % (job, release),
        'params': job_params,
        'enable_dedup': False

    }'''
    params = {}
    params["queue"] = "aria-job_worker-small"
    params["priority"] = "5"
    params["name"] = job_name
    params["tags"] = ["%s" % dataset_tag]
    params["type"] = 'job-%s:%s' % (job, release)
    params["params"] = job_params
    params["enable_dedup"] = False
    print('submitting jobs with params:')
    print(json.dumps(params, sort_keys=True,indent=4, separators=(',', ': ')))
    r = requests.post(job_submit_url, params=json.dumps(params), verify=False)
    if r.status_code != 200:
        r.raise_for_status()
    result = r.json()
    if 'result' in result.keys() and 'success' in result.keys():
        if result['success'] == True:
            job_id = result['result']
            print 'submitted create_aoi:%s job: %s job_id: %s' % (release, job_id)
        else:
            print 'job not submitted successfully: %s' % result
            raise Exception('job not submitted successfully: %s' % result)
    else:
        raise Exception('job not submitted successfully: %s' % result)

	

def get_met_file(AOI_name, event_type, event_time, use_case, ctx):
	file_met_location = ''
	event = ''
	dataset = ctx['AOI_type']

	if use_case == "event_response":
		priority = '7'
		file_met_location = "event_response/AOI.met.json"
	elif use_case == "monitor_rules":
		priority = '4'
		file_met_location = "monitor_rules/AOI.met.json"
	elif use_case == "no_rules":
		priority = '8'
		dataset = ctx['AOI_type']
		file_met_location = "create/AOI.met.json"
		if ctx['AOI_type'] != "monitoring":
			api_priority = '7'
			asf_priority = '7'
			scihub_priority = '7'
		else:
			api_priority = '5'
                	asf_priority = '5'
                	scihub_priority = '5'

		if ctx['event_time']!="":
			asf_start_time = ',\n"starttime" : "event -14 days"'
			asf_end_time = ',\n"endtime" : "now"'
			scihub_start_time = ',\n"starttime" : "event -14 days"'
			scihub_end_time = ',\n"endtime" : "now"'
			event = ',\n "event": { \n "type": "'+ctx['event_type']+'", \n "time": "'+ctx['event_time']+'"}'
		else:
			asf_start_time = ""
			asf_end_time = ""
			scihub_start_time = ""
			scihub_end_time = ""
			event = ""
	elif use_case == "chr_pair":
		priority = '7'
		file_met_location = "PDL/AOI.met.json"
	

	print("The file_met_location is %s",file_met_location)
	file_met = open(os.path.join(BASE_PATH, file_met_location)).read()
	met_temp = Template( file_met)

	if use_case == "monitor_rules":
		met_data =met_temp.substitute({'priority':'"'+priority+'"'})
	elif use_case == "no_rules":
		met_data =met_temp.substitute({'priority':int(priority),'apihub_priority':int(api_priority),'asf_priority':int(asf_priority),'scihub_priority':int(scihub_priority), 'dataset':'"'+dataset+'"', 'event':event})

	elif use_case == "event_response" or use_case == "chr_pair":
		event_time = event_time #.strftime("%Y-%m-%dT%H:%M:%S")+'"'
		event_type = event_type
		met_data = met_temp.substitute({'priority':'"'+priority+'"', 'event_type':'"'+event_type+'"', 'event_time':'"'+ event_time+'"'})

	filename = AOI_name+'/'+AOI_name+'.met.json'
	with open(filename, 'w+') as f:
		f.write(met_data)
	logger.debug("AOI met file created")
	print ("AOI met file created")

def get_dataset_file(AOI_name, label, coordinates, start_time, end_time,  use_case):

	file_datasets_location = ''
	end_query = ""

	if use_case == "event_response":
                file_datasets_location = "event_response/AOI.datasets.json"
        elif use_case == "monitor_rules":
                file_datasets_location = "monitor_rules/AOI.datasets.json"
	elif use_case == "chr_pair":
                file_datasets_location = "PDL/AOI.datasets.json"
	elif use_case == "no_rules":
		file_datasets_location = "create/AOI.datasets.json"

	file_dataset = open(os.path.join(BASE_PATH, file_datasets_location)).read()
	dataset_temp = Template(file_dataset)

	if use_case == "event_response" or use_case == "chr_pair":
		dataset_data = dataset_temp.substitute({'label':'"'+label+'"','coordinates':coordinates,'start_time':'"'+start_time+'"','end_time':'"'+end_time+'"'})
	elif use_case == "monitor_rules":
		if end_time != "":
			end_time = ', \n "endtime": "'+end_time+'"'
		dataset_data = dataset_temp.substitute({'label':'"'+label+'"','coordinates':coordinates,'start_time':'"'+start_time+'"','end_time':end_time})
	elif use_case == "no_rules":
		if end_time != "":
			end_time = ',\n"endtime": "'+end_time+'"'
		dataset_data = dataset_temp.substitute({'label':'"'+label+'"','coordinates':coordinates,'start_time':'"'+start_time+'"','end_time':end_time})
	filename = AOI_name+'/'+AOI_name+'.dataset.json'
	with open(filename, 'w+') as f:
                f.write(dataset_data)
	logger.debug("AOI datasets file created")
	print ("AOI datasets file created")

def get_browser_png(img_URL):
	
	if img_URL != '':
		try:
			osaka.main.get(img_URL,'./browse.img')
			os.system ("cp %s %s" % ('./browse.img', AOI_name+"/browse.png"))
		except:
			os.system ("cp %s %s" % ('default.img', AOI_name+"/browse.png"))
	else:
		os.system ("cp %s %s" % ('default.img', AOI_name+"/browse.png"))		
	os.system ("convert -resize 250x250 %s %s" % (AOI_name+"/browse.png", AOI_name+"/browse_small.png"))

def get_AOI(AOI_name):
	logger.debug("Going to query ES for AOI")
	es_url = app.conf["GRQ_ES_URL"]
	index = app.conf["DATASET_ALIAS"]
	query_string = {"query":{"bool": {"must": [{"term": {"dataset_type.raw": "area_of_interest"}},{"query_string": {"query": '_id:"AOI"',"default_operator": "OR"}}]}}}
	query_string["query"]["bool"]["must"][1]["query_string"]["query"] = '_id:"'+AOI_name+'"'
	r = requests.post('%s/%s/_search?' % (es_url, index), json.dumps(query_string))
	return r

def update_redis(AOI_name, start_time):
	#construct redis update commands
	for types in ['unavco', 'scihub', 'asf']:
		redis_cmd =  'redis-cli set %s-%s-last_query %s' % (AOI_name, types, start_time)
		print redis_cmd
		logger.debug(redis_cmd)
		os.system(redis_cmd)
	
def rule_generation(open_ended, dataset_type, track_number, start_time, end_time, coordinates, passthrough):
	pass_obj = passthrough
	
	if 'bool' in pass_obj:
		subs_pass = pass_obj['bool']['must']
		pass_str = json.dumps(subs_pass)+','
	else:
		pass_str = ''
	
	if track_number == 'not_specified':
		track_condition = ''
	else:
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

	if open_ended is False:
		file_rule = open(os.path.join(BASE_PATH, 'ifg_query.json'))
		rule_query_temp = Template( file_rule.read())
		rule_query = rule_query_temp.substitute({'dataset_type':dataset_type,'passthrough':pass_str, 'track_number':track_condition ,'start_time':'"'+start_time+'"','end_time':'"'+end_time+'"', 'coordinates':json.dumps(coordinates)})
        else:
		file_rule = open(os.path.join(BASE_PATH, 'open_ended_query.json'))
		rule_query_temp = Template( file_rule.read())
		rule_query = rule_query_temp.substitute({'dataset_type':dataset_type,'passthrough':pass_str, 'track_number':track_condition ,'start_time':'"'+start_time+'"', 'coordinates':json.dumps(coordinates)})

	logger.debug("Rule generation query:\n %s"%rule_query)
	print "Rule generation query:\n %s"%rule_query
	return rule_query

def co_event_rule(passthrough, dataset_type, track_number, event_time, coordinates):
	pass_obj = passthrough

        if 'bool' in pass_obj:
                subs_pass = pass_obj['bool']['must']
                pass_str = json.dumps(subs_pass)+','
        else:
                pass_str = ''

	if track_number == 'not_specified':
                track_condition = ''
        else:
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

	co_seismic_rule = open(os.path.join(BASE_PATH, 'co_event_condition.json'))
        rule_temp = Template( co_seismic_rule.read())

	coordinates = str(coordinates).replace("u'","\"")
        coordinates = coordinates.replace("'","\"")

        co_seismic_query = rule_temp.substitute({'passthrough':pass_str, 'track_number':track_condition, 'dataset_type':'"'+dataset_type+'"' ,'event_time1':'"'+event_time+'"', 'event_time2':'"'+event_time+'"', 'coordinates':coordinates})
	print "co_seismic_query:\n"
	print co_seismic_query
        return co_seismic_query

def add_rule(mode, open_ended, AOI_name, coordinates, workflow, workflow_version, projectName, start_time, event_time, end_time, temporal_baseline, track_number, passthrough, minMatch, azimuth_looks, filter_strength, dem_type, range_looks, coverage_threshold, dataset_tag, priority):
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
	elif workflow.find("cod") != -1:
		rule_name = mode+'cod_'+AOI_name

        logger.debug("Kicking off rules for response: %s"%rule_name)
        print("Kicking off rules for response: %s"%rule_name)

	if workflow.endswith("lar"):
		event_rule = rule_generation(open_ended, '"S1-SLCP"', track_number, start_time, end_time, coordinates, passthrough)
		other_params = {}
	elif workflow.endswith("ifg"):
		event_rule = rule_generation(open_ended, '"S1-IW_SLC"', track_number, start_time, end_time, coordinates, passthrough)
        	other_params = {"dataset_tag":dataset_tag,"project":projectName , "singlesceneOnly": "true", "preReferencePairDirection": "backward", "postReferencePairDirection": "forward", "temporalBaseline":temporal_baseline,"minMatch":minMatch, "azimuth_looks":azimuth_looks, "filter_strength":filter_strength, "dem_type":dem_type, "range_looks":range_looks, "covth":coverage_threshold, "precise_orbit_only":"false"}
	elif workflow.endswith("slcp-mrpe"):
		event_rule = rule_generation(open_ended, '"S1-IW_SLC"', track_number, start_time, end_time, coordinates, passthrough)
		other_params = {"event_time":event_time, "start_time":start_time, "end_time":end_time, "dataset_tag":dataset_tag, "project":projectName, "singlesceneOnly": "true", "temporalBaseline":temporal_baseline, "minMatch":minMatch, "covth":coverage_threshold, "precise_orbit_only":"false", "azimuth_looks":azimuth_looks, "filter_strength":filter_strength, "dem_type":dem_type, "range_looks":range_looks}
	elif workflow.find("cod") != -1:
		event_rule = rule_generation(open_ended, '"S1-SLCP"', track_number, start_time, end_time, coordinates, passthrough)
		other_params = {"dataset_tag":dataset_tag, "project": projectName, "slcp_version":slcp_product_version, "temporal_baseline": temporal_baseline, "aoi_name":AOI_name}

        logger.debug("Going to add "+mode+"rule for "+workflow)
        logger.debug("Rule names: %s"% rule_name)
        logger.debug("workflows: %s"% workflow_name)
        logger.debug("priority: %s"% str(priority))
        logger.debug("rule: %s"% event_rule)
        logger.debug("other params: %s"% other_params)

        print("Going to add %s rule for %s"% (mode,workflow))
        print("Rule names: %s"% rule_name)
        print("workflows: %s"% workflow_name)
        print("priority: %s"% str(priority))
        print("rule: %s"% event_rule)
        print("other params: %s"% other_params)

        rules_info = "Added "+mode+"rule \n"
        rules_info += "Rule name: %s"% rule_name+'\n'
        rules_info += "workflow: %s"% workflow_name+'\n'
        rules_info += "priority: %s"% str(priority)+'\n'
        #rules_info += "event_rule: %s"% event_rule+"\n"
        #rules_info += "other params: %s"% other_params+'\n'

        add_user_rules.add_user_rule(projectName, rule_name, workflow_name, priority, event_rule, other_params)
        logger.debug(mode+"rule added")
        print(mode+"rule added")

        if workflow.endswith("slcp-mrpe") or workflow.endswith("ifg"):
	    other_params["auto_bbox"] = "true"
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

	logger.debug("Kicking off rules for response: %s"%rule_name)
        print("Kicking off rules for response: %s"%rule_name)

        logger.debug("Going to add "+mode+"rule for "+workflow)
        logger.debug("Rule names: %s"% rule_name)
        logger.debug("workflows: %s"% workflow_name)
        logger.debug("priority: %s"% str(priority))
        logger.debug("rule: %s"% event_rule)
        logger.debug("other params: %s"% other_params)

        print("Going to add %s rule for %s"% (mode,workflow))
        print("Rule names: %s"% rule_name)
        print("workflows: %s"% workflow_name)
        print("priority: %s"% str(priority))
        print("rule: %s"% event_rule)
        print("other params: %s"% other_params)

        rules_info = "Added "+mode+"rule \n"
        rules_info += "Rule name: %s"% rule_name+'\n'
        rules_info += "workflow: %s"% workflow_name+'\n'
        rules_info += "priority: %s"% str(priority)+'\n'
        #rules_info += "event_rule: %s"% event_rule+"\n"
        #rules_info += "other params: %s"% other_params+'\n'

        add_user_rules.add_user_rule(projectName, rule_name, workflow_name, priority, event_rule, other_params)
        logger.debug(mode+"rule added")
        print(mode+"rule added")

        return rules_info


def add_email_rule(AOI_name, dataset, track_number, passthrough, event_time, coordinates):

	if dataset == "S1-SLCP":
		product_type = "slcp"
	elif dataset == "S1-IFG":
		product_type = "ifg"
	elif dataset == "S1-LAR":
		product_type = "lar"
	elif dataset == "S1-COD":
		product_type = "cod"

	email_rule_set = co_event_rule(passthrough, dataset, track_number, event_time, json.dumps(coordinates))
        other_params = {"emails": email}

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

def mega_rules(AOI_name, coordinates, slcp_rule, lar_rule, ifg_rule, cod_rule, slcp_workflow, lar_workflow, ifg_workflow, cod_workflow, slcp_workflow_version, lar_workflow_version, ifg_workflow_version, cod_workflow_version, projectName, start_time, end_time, event_time, temporal_baseline, track_number, passthrough, minMatch, range_looks, azimuth_looks, filter_strength, dem_type, coverage_threshold, dataset_tag, emails):

	rule_names = []
	rules_info = ''
	ifg_workflow_name = ifg_workflow+":"+ifg_workflow_version
	slcp_workflow_name = slcp_workflow+":"+slcp_workflow_version
        lar_workflow_name = lar_workflow+":"+lar_workflow_version
	cod_workflow_name = cod_workflow+":"+cod_workflow_version
	#check if event time exists
	if end_time != '':
		if event_time == '':
			# event_time doesn't exist
			#set trigger rules from starttime and endtime of AOI
			if ifg_rule == True:
				rules_info += add_rule('', False, AOI_name, coordinates, ifg_workflow, ifg_workflow_version, projectName, start_time, "", end_time, temporal_baseline, track_number, passthrough, minMatch, azimuth_looks, filter_strength, dem_type, range_looks, coverage_threshold, dataset_tag, 4)
				rule_names.extend(['ifg_'+AOI_name])
			if slcp_rule == True:
                                rules_info += add_rule('', False, AOI_name, coordinates, slcp_workflow, slcp_workflow_version, projectName, start_time, "", end_time, temporal_baseline, track_number, passthrough, minMatch, azimuth_looks, filter_strength, dem_type, range_looks, coverage_threshold, dataset_tag, 4)
				rule_names.extend(['slcp_'+AOI_name])
			if lar_rule == True:
                                rules_info += add_rule('', False, AOI_name, coordinates, lar_workflow, lar_workflow_version, projectName, start_time, "", end_time, temporal_baseline, track_number, passthrough, minMatch, azimuth_looks, filter_strength, dem_type, range_looks, '', dataset_tag, 4)
				rule_names.extend(['lar_'+AOI_name])
			if cod_rule == True:
				# if it's a not event the don't add cod rule
				print "COD rules are only added for events. So ignoreing COD_processing set to true flag."
				#rules_info += add_rule('', False, AOI_name, coordinates, cod_workflow, cod_workflow_version, projectName, start_time, "", end_time, temporal_baseline, track_number, passthrough, '', '', '', '', '', 4) 
		else:
			#add pre-event, post-event and co-event trigger rules
			if ifg_rule == True:
				#add pre-event rule
				rules_info += add_rule('pre-event-', False, AOI_name, coordinates, ifg_workflow, ifg_workflow_version, projectName, start_time, "", event_time, temporal_baseline, track_number, passthrough, minMatch, azimuth_looks, filter_strength, dem_type, range_looks, coverage_threshold, dataset_tag, 7)
			
				#add post-event rule
				rules_info += add_rule('post-event-', False, AOI_name, coordinates, ifg_workflow, ifg_workflow_version, projectName, event_time, "", end_time, temporal_baseline, track_number, passthrough, minMatch, azimuth_looks, filter_strength, dem_type, range_looks, coverage_threshold, dataset_tag,7)
				rule_names.extend(['pre-event-ifg_'+AOI_name, "post-event-ifg_"+AOI_name])
				#add mail rule
				rules_info += add_email_rule(AOI_name, "S1-IFG", track_number, passthrough, event_time, coordinates)
				rule_names.extend([AOI_name+"-ifg_email"])
			if slcp_rule == True:
				rules_info += add_rule('event-', False, AOI_name, coordinates, slcp_workflow, slcp_workflow_version, projectName, start_time, event_time, end_time, temporal_baseline, track_number, passthrough, minMatch, azimuth_looks, filter_strength, dem_type, range_looks, coverage_threshold, dataset_tag, 7)
				rule_names.extend(["event-slcp_"+AOI_name, "post-event-slcp_"+AOI_name])
				#add email rule
				rules_info += add_email_rule(AOI_name, "S1-SLCP", track_number, passthrough, event_time, coordinates)
				rule_names.extend([AOI_name+"-slcp_email"])
			if lar_rule == True:
				event_rule = co_event_rule(passthrough, "S1-SLCP", track_number, event_time, coordinates)
				rules_info += add_co_event_lar(event_rule, projectName, AOI_name, lar_workflow, lar_workflow_version, 7)
				rule_names.extend(["co-event-lar_"+AOI_name])
				#add email rule
				rules_info += add_email_rule(AOI_name, "S1-LAR", track_number, passthrough, event_time, coordinates)
				rule_names.extend([AOI_name+"-lar_email"])
			if cod_rule == True:
                                #add event rule
                                rules_info += add_rule('event-', False, AOI_name, coordinates, cod_workflow, cod_workflow_version, projectName, start_time, "", end_time, temporal_baseline, track_number, passthrough, '', '', '', '', '', '', dataset_tag, 7)
                        
                                rule_names.extend(['event-cod_'+AOI_name])
                                #add mail rule
                                rules_info += add_email_rule(AOI_name, "S1-COD", track_number, passthrough, event_time, coordinates)
                                rule_names.extend([AOI_name+"-cod_email"])
	else:
		logging.debug("Start time exists but no end time specified")
		if event_time == '':
			#only start time give
			logging.debug("Only start time available")
			if ifg_rule:
				rules_info += add_rule('', True, AOI_name, coordinates, ifg_workflow, ifg_workflow_version, projectName, start_time, '', '', temporal_baseline, track_number, passthrough, minMatch, azimuth_looks, filter_strength, dem_type, range_looks, coverage_threshold, dataset_tag, 4)
				rule_names.extend(['ifg_'+AOI_name])
			if slcp_rule:
                                rules_info += add_rule('', True, AOI_name, coordinates, slcp_workflow, slcp_workflow_version, projectName, start_time, '', '', temporal_baseline, track_number, passthrough, minMatch, azimuth_looks, filter_strength, dem_type, range_looks, coverage_threshold, dataset_tag, 4)
                                rule_names.extend(['slcp_'+AOI_name])
			if lar_rule:
                                rules_info += add_rule('', True, AOI_name, coordinates, lar_workflow, lar_workflow_version, projectName, start_time, '', '', temporal_baseline, track_number, passthrough, minMatch, azimuth_looks, filter_strength, dem_type, range_looks, "", dataset_tag, 4)
                                rule_names.extend(['lar_'+AOI_name])
                        if cod_rule:
				#not adding COD because this is not an event
                                print "COD rules are only added for events. So ignoreing COD_processing set to true flag."
				#rule_names.extend(['cod_'+AOI_name])
		else:
			#start time and event time given
			logging.debug("Need to add a pre-event and post event needs to be added")
			if ifg_rule == True:
                                #add pre-event rule
                                rules_info += add_rule('pre-event-', False, AOI_name, coordinates, ifg_workflow, ifg_workflow_version, projectName, start_time, '', event_time, temporal_baseline, track_number, passthrough, minMatch, azimuth_looks, filter_strength, dem_type, range_looks, coverage_threshold, dataset_tag, 7)

                                #add post-event rule
                                rules_info += add_rule('post-event-', True, AOI_name, coordinates, ifg_workflow, ifg_workflow_version, projectName, event_time, '', '', temporal_baseline, track_number, passthrough, minMatch, azimuth_looks, filter_strength, dem_type, range_looks, coverage_threshold, dataset_tag,7)
                                rule_names.extend(['pre-event-ifg_'+AOI_name, "post-event-ifg_"+AOI_name])
                                #add mail rule
				rules_info += add_email_rule(AOI_name, "S1-IFG", track_number, passthrough, event_time, coordinates)
				rule_names.extend([AOI_name+"-ifg_email"])

			if slcp_rule == True:
                                rules_info += add_rule('pre-event-', False, AOI_name, coordinates, slcp_workflow, slcp_workflow_version, projectName, start_time, '', event_time, temporal_baseline, track_number, passthrough, minMatch, azimuth_looks, filter_strength, dem_type, range_looks, coverage_threshold, dataset_tag, 7)
                                
                                rules_info += add_rule('post-event-', True, AOI_name, coordinates, slcp_workflow, slcp_workflow_version, projectName, event_time, '', '', temporal_baseline, track_number, passthrough, minMatch, azimuth_looks, filter_strength, dem_type, range_looks, coverage_threshold, dataset_tag, 7)
                                rule_names.extend(["pre-event-slcp_"+AOI_name, "post-event-slcp_"+AOI_name])
                                #add email rule
                                rules_info += add_email_rule(AOI_name, "S1-SLCP", track_number, passthrough, event_time, coordinates)
                                rule_names.extend([AOI_name+"-slcp_email"])

			if lar_rule == True:
                                rules_info += co_event_rule(passthrough, "S1-LAR", track_number, event_time, coordinates)
				rule_names.extend(["co-event-lar_"+AOI_name])
                                #add email rule
                                rules_info += add_email_rule(AOI_name, "S1-LAR", track_number, passthrough, event_time, coordinates)
                                rule_names.extend([AOI_name+"-lar_email"])

			if cod_rule == True:
                                rules_info += add_rule('event-', False, AOI_name, coordinates, cod_workflow, cod_workflow_version, projectName, start_time, '', '', temporal_baseline, track_number, passthrough, '', '', '', '', dataset_tag, 7)

                                rule_names.extend(["event-cod_"+AOI_name])
                                #add email rule
                                rules_info += add_email_rule(AOI_name, "S1-COD", track_number, passthrough, event_time, coordinates)
                                rule_names.extend([AOI_name+"-cod_email"])	
	#send out email to admin	
	logger.debug("Sending email to admin with details of rules created")
        print("Sending email to admin with details of rules created")
	if emails != '':
        	email_to_user(AOI_name, emails, "mega", projectName, rule_names, rules_info)
		logger.debug("Email sent to admin")
        	print("Email sent to admin")

	#end of mega_rules

if __name__ == "__main__":
    '''
    Main program of purge_products
    '''
    with open('_context.json') as f:
      ctx = json.load(f)
    
    use_case = ctx['use_case']

    if use_case == 'no_rules':
    	projectName = ctx['project_name']
    	AOI_name = ctx['AOI_name']
    	label = ctx['label']
    	coordinates = json.dumps(ctx['coordinates'])
    	event_type = ctx['event_type']
    	event_time = ctx['event_time']
    	start_time = ctx['start_time']
    	end_time = ctx['end_time']
    	use_case =  ctx['use_case']
	emails = ctx['emails']
	img_URL = ctx['img_URL']
    	AOI_name = "AOI_"+AOI_name
    	AOI_dir = AOI_name
    
    	# create the AOI folder
    	if not os.path.exists(AOI_dir):
            os.makedirs(AOI_dir)

    	get_met_file(AOI_name, event_type, event_time, use_case, ctx)
    	get_dataset_file(AOI_name, label, coordinates, start_time, end_time, use_case)
    	get_browser_png(img_URL)

	AOI_info = 'Hi, \n'
        AOI_info += 'A new AOI named '+AOI_name+' has been added to the system using the Add AOI action.\n'
        AOI_info += 'You can find the met.json and dataset.json attached in this email.\n'

	if emails != "":	
		email_to_user(AOI_name, emails, "no_rules", projectName, '', AOI_info)
	#update_redis(AOI_name, start_time)
    	#STOP here if only creating AOI
    	# the AOI ingestion is taken care of by verdi.

    if use_case != 'no_rules':
    	#assigning variables for rules
    	track_number = ctx['track_number']
    	temporal_baseline = ctx['temporal_baseline']
    	condition_query = ctx['query'] # need this to get the faceted on dataset name
    	minMatch = ctx['minimum_pair']

    	if use_case == 'chr_pair':
		slcp_workflow = ctx['slcp_workflow']
		lar_workflow = ctx['lar_workflow']
		slcp_workflow_version = ctx['SLCP_workflow_version']
		lar_workflow_version = ctx['LAR_workflow_version']
    	elif use_case == 'monitor_rules':
		slcp_workflow = ctx['slcp_workflow']
        	lar_workflow = ctx['lar_workflow']
        	slcp_workflow_version = ctx['SLCP_workflow_version']
        	lar_workflow_version = ctx['LAR_workflow_version']
		ifg_workflow = ctx['ifg_workflow']
        	ifg_workflow_version = ctx['IFG_workflow_version']
    	else:
		ifg_workflow = ctx['ifg_workflow']
		workflow_version = ctx['IFG_workflow_version']

    	if use_case!='monitor_rules':
		email = ctx['emails']

    	if use_case != 'chr_pair':
    		if ifg_workflow == 'hysds-io-sciflo-s1-ifg':
			range_looks =  ctx['range_looks']
			azimuth_looks = ctx['azimuth_looks']
			dataset_tag =  ctx['AOI_type']
   
    	# now let's add user rules
    	# workflow is the name of the hysds-io tosca action and version number, needs to be inputted by the operator
	if use_case == 'mega':
		user_name = ctx['username']
		name = ctx['name']
		AOI_name = ctx['AOI_name']
		projectName = ctx['project_name']	
		starttime = ''
		endtime = ''
		eventtime = ''

		ifg = ctx['IFG_processing']
		slcp = ctx['SLCP_processing']
		lar = ctx['LAR_processing']
		cod = ctx['COD_processing']

		ifg_workflow = ctx['ifg_workflow']
		slcp_workflow= ctx['slcp_workflow']
                lar_workflow = ctx['lar_workflow']
                cod_workflow = ctx['cod_workflow']

		ifg_version = ctx['IFG_workflow_version']
		slcp_version = ctx['SLCP_workflow_version']
		lar_version = ctx['LAR_workflow_version']
                cod_version = ctx['COD_workflow_version']

		azimuth_looks = ctx['azimuth_looks']
		range_looks = ctx['range_looks']
		filter_strength = ctx["filter_strength"]
		dem_type = ctx["dem_type"]
		emails = ctx['emails']
		passthrough = ctx['query']
		coverage_threshold = ctx['coverage_threshold']
		dataset_tag = ctx['dataset_tag']
		track_number = ctx['track_number']

		r = get_AOI(AOI_name)
		if r.status_code != 200:
        	        print("Failed to query ES. Got status code %d:\n%s" %(r.status_code, json.dumps(r.json(), indent=2)))
                	logger.debug("Failed to query ES. Got status code %d:\n%s" %
                         (r.status_code, json.dumps(r.json(), indent=2)))
        	r.raise_for_status()
        	logger.debug("result: %s" % r.json())
        	# check if AOI has event_time specified.
        	# mine out the start, end and event time.
        	result = r.json()
		coordinates =  result["hits"]["hits"][0]["_source"]["location"]	
        	starttime = result["hits"]["hits"][0]["_source"]["starttime"]
        	if 'endtime' not in result["hits"]["hits"][0]["_source"]:
                	logger.info("AOI doesn't have associated endtime")
        	else:
                	endtime = result["hits"]["hits"][0]["_source"]["endtime"]
        	if 'event' not in result["hits"]["hits"][0]["_source"]["metadata"]:
                	logger.info("AOI doesn't have associated eventtime")
        	else:
                	eventtime = result["hits"]["hits"][0]["_source"]["metadata"]["event"]["time"]
		
		mega_rules(AOI_name, coordinates, slcp, lar, ifg, cod, slcp_workflow, lar_workflow, ifg_workflow, cod_workflow, slcp_version, lar_version, ifg_version, cod_version, projectName, starttime, endtime, eventtime, temporal_baseline, track_number, passthrough, minMatch, range_looks, azimuth_looks, filter_strength, dem_type, coverage_threshold, dataset_tag, emails)					
