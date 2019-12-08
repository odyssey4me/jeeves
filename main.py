#!/usr/bin/python3

import sys
import yaml
import jinja2
import jenkins
import bugzilla
import datetime
from jira import JIRA

from smtplib import SMTP
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# function definitions
def get_bug():

	# get all bugs for job from YAML file
	try:
		with open("blockers.yaml", 'r') as file:
			bug_file = yaml.safe_load(file)
			bugs = bug_file[job_name]['bz']
	except Exception as e:
		print("Error loading blocker configuration data: ", e)
		bug_list = [{'bug_name': "Could not find relevant bug", 'bug_url': None}]
	else:

		# initialize bug list
		bug_list = []

		# get bugzilla info from bugzilla API
		for bug_id in bugs:

			# 0 should be default in YAML file (i.e. no bugs recorded)
			# if there is a 0 entry then that should be the only "bug", so break
			if bug_id == 0:
				bug_list = [{'bug_name': 'No bug on file', 'bug_url': None}]
				break

			try:
				bz_api = bugzilla.Bugzilla(config['bugzilla_url'])
				bug = bz_api.getbug(bug_id)
				bug_name = bug.summary
			except Exception as e:
				print("Bugzilla API Call Error: ", e)
				bug_name = "{}: Bugzilla API Call Error".format(bug_id)
			finally:
				bug_url = config['bugzilla_url'] + "/show_bug.cgi?id=" + str(bug_id)
				bug_list.append(
					{
						'bug_name': bug_name, 
						'bug_url': bug_url
					}
				)

	return bug_list

def get_jira():

	# get all tickets for job from YAML file
	try:
		with open("blockers.yaml", 'r') as file:
			jira_file = yaml.safe_load(file)
			tickets = jira_file[job_name]['jira']
	except Exception as e:
		print("Error loading blocker configuration data: ", e)
		ticket_list = [{'ticket_name': "Could not find relevant ticket", 'ticket_url': None}]
	else:

		# initialize bug list
		ticket_list = []

		# get bugzilla info from bugzilla API
		for ticket_id in tickets:

			# 0 should be default in YAML file (i.e. no tickers recorded)
			# if there is a 0 entry then that should be the only "ticket", so break
			if ticket_id == 0:
				ticket_list = [{'ticket_name': 'No ticket on file', 'ticket_url': None}]
				break

			try:
				issue = jira.issue(ticket_id)
				ticket_name = issue.fields.summary
			except Exception as e:
				print("Jira API Call Error: ", e)
				ticket_name = "{}: Jira API Call Error".format(ticket_id)
			finally:
				ticket_url = config['jira_url'] + "/browse/" + str(ticket_id)
				ticket_list.append(
					{
						'ticket_name': ticket_name, 
						'ticket_url': ticket_url
					}
				)

	return ticket_list

def get_osp_version(job_name):
	x = len(config['job_search_field']) + 1
	y = len(config['job_search_field']) + 3
	return job_name[x:y]

def percent(part, whole):
	return round(100 * float(part)/float(whole), 1)

# load configuration data
if len(sys.argv) == 1:
	conf = "config.yaml"
elif len(sys.argv) == 2:
	conf = sys.argv[1]
else:
	print("Improper number of arguments - please see README")
	sys.exit()

try:
	with open(conf, 'r') as file:
		config = yaml.safe_load(file)
except Exception as e:
	print("Error loading configuration data: ", e)
	sys.exit()

# connect to Jira
try:
	options = {
				"server": config['jira_url'],
				"verify": config['certificate']
	}
	jira = JIRA(options)
except Exception as e:
	print("Error connecting to Jira: ", e)
	sys.exit()

# connect to jenkins server
try:
	server = jenkins.Jenkins(config['jenkins_url'], username=config['username'], password=config['api_token'])
	user = server.get_whoami()
	version = server.get_version()
except Exception as e:
	print("Error connecting to Jenkins server: ", e)
	sys.exit()
else:
	user_email_address = user['property'][-1]['address']
	header = "Report generated by {} from Jenkins {} on {}".format(user_email_address, version, datetime.datetime.now())

# fetch relevant jobs from server
jobs = server.get_jobs()
jobs = [job for job in jobs if config['job_search_field'] in job['name']]

# initialize python variables
num_jobs = len(jobs)
num_success = 0
num_unstable = 0
num_failure = 0
num_error = 0
rows = []

# collect info from all relevant jobs
for job in jobs[::-1]:
	job_name = job['name']
	osp_version = get_osp_version(job_name)
	try:
		job_info = server.get_job_info(job_name)
		job_url = job_info['url']
		lcb_num = job_info['lastCompletedBuild']['number']
		lcb_url = job_info['lastCompletedBuild']['url']
		build_info = server.get_build_info(job_name, lcb_num)
		lcb_result = build_info['result']
	except Exception as e:
		print("Jenkins API call error: ", e)
		continue

	if lcb_result == "SUCCESS":
		num_success += 1
		bug_list = [{'bug_name': 'N/A', 'bug_url': None}]
		ticket_list = [{'ticket_name': 'N/A', 'ticket_url': None}]
	elif lcb_result == "UNSTABLE":
		num_unstable += 1
		bug_list = get_bug()
		ticket_list = get_jira()
	elif lcb_result == "FAILURE":
		num_failure += 1
		bug_list = get_bug()
		ticket_list = get_jira()
	else:
		num_error += 1

	row = {'osp_version': osp_version,
			'job_name': job_name,
			'job_url': job_url,
			'lcb_num': lcb_num,
			'lcb_url': lcb_url,
			'lcb_result': lcb_result,
			'bug_list': bug_list,
			'ticket_list': ticket_list
	}

	rows.append(row)

# calculate summary
total_success = "Total SUCCESS:  {}/{} = {}%".format(num_success, num_jobs, percent(num_success, num_jobs))
total_unstable = "Total UNSTABLE: {}/{} = {}%".format(num_unstable, num_jobs, percent(num_unstable, num_jobs))
total_failure = "Total FAILURE:  {}/{} = {}%".format(num_failure, num_jobs, percent(num_failure, num_jobs))
if num_error > 0:
	total_error = "Total ERROR:  {}/{} = {}%".format(num_failure, num_jobs, percent(num_error, num_jobs))
else:
	total_error = False

# initialize jinja2 vars
loader = jinja2.FileSystemLoader('./template.html')
env = jinja2.Environment(loader=loader)
template = env.get_template('')

# generate HTML report
htmlcode = template.render(header=header, rows=rows, total_success=total_success, total_unstable=total_unstable, total_failure=total_failure, total_error=total_error)

# construct email
msg = MIMEMultipart()
msg['From'] = user_email_address
msg['Subject'] = config['email_subject']
msg['To'] = config['email_to']
msg.attach(MIMEText(htmlcode, 'html'))

# create SMTP session
with SMTP(config['smtp_host']) as smtp:

	# start TLS for security
	smtp.starttls()

	# use ehlo or helo if needed
	smtp.ehlo_or_helo_if_needed()

	# send email
	smtp.sendmail(msg["From"], msg["To"], msg.as_string())
