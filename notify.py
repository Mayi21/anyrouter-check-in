import base64
import json
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Literal

import httpx
import requests


class NotificationKit:
	def __init__(self):
		self.email_user: str = os.getenv('EMAIL_USER', '')
		self.email_pass: str = os.getenv('EMAIL_PASS', '')
		self.email_to: str = os.getenv('EMAIL_TO', '')
		self.pushplus_token = os.getenv('PUSHPLUS_TOKEN')
		self.server_push_key = os.getenv('SERVERPUSHKEY')
		self.dingding_webhook = os.getenv('DINGDING_WEBHOOK')
		self.feishu_webhook = os.getenv('FEISHU_WEBHOOK')
		self.weixin_webhook = os.getenv('WEIXIN_WEBHOOK')
		self.webhook_url = os.getenv('WEBHOOK_URL')
		self.webhook_headers = os.getenv('WEBHOOK_HEADERS', '{}')

	def send_email(self, title: str, content: str, msg_type: Literal['text', 'html'] = 'text'):
		if not self.email_user or not self.email_pass or not self.email_to:
			raise ValueError('Email configuration not set')

		msg = MIMEMultipart()
		msg['From'] = f'AnyRouter Assistant <{self.email_user}>'
		msg['To'] = self.email_to
		msg['Subject'] = title

		body = MIMEText(content, msg_type, 'utf-8')
		msg.attach(body)

		smtp_server = f'smtp.{self.email_user.split("@")[1]}'
		with smtplib.SMTP_SSL(smtp_server, 465) as server:
			server.login(self.email_user, self.email_pass)
			server.send_message(msg)

	def send_pushplus(self, title: str, content: str):
		if not self.pushplus_token:
			raise ValueError('PushPlus Token not configured')

		data = {'token': self.pushplus_token, 'title': title, 'content': content, 'template': 'html'}
		with httpx.Client(timeout=30.0) as client:
			client.post('http://www.pushplus.plus/send', json=data)

	def send_serverPush(self, title: str, content: str):
		if not self.server_push_key:
			raise ValueError('Server Push key not configured')

		data = {'title': title, 'desp': content}
		with httpx.Client(timeout=30.0) as client:
			client.post(f'https://sctapi.ftqq.com/{self.server_push_key}.send', json=data)

	def send_dingtalk(self, title: str, content: str):
		if not self.dingding_webhook:
			raise ValueError('DingTalk Webhook not configured')

		data = {'msgtype': 'text', 'text': {'content': f'{title}\n{content}'}}
		with httpx.Client(timeout=30.0) as client:
			client.post(self.dingding_webhook, json=data)

	def send_feishu(self, title: str, content: str):
		if not self.feishu_webhook:
			raise ValueError('Feishu Webhook not configured')

		data = {
			'msg_type': 'interactive',
			'card': {
				'elements': [{'tag': 'markdown', 'content': content, 'text_align': 'left'}],
				'header': {'template': 'blue', 'title': {'content': title, 'tag': 'plain_text'}},
			},
		}
		with httpx.Client(timeout=30.0) as client:
			client.post(self.feishu_webhook, json=data)

	def send_wecom(self, title: str, content: str):
		if not self.weixin_webhook:
			raise ValueError('WeChat Work Webhook not configured')

		data = {'msgtype': 'text', 'text': {'content': f'{title}\n{content}'}}
		with httpx.Client(timeout=30.0) as client:
			client.post(self.weixin_webhook, json=data)

	def send_webhook(self, title: str, content: str):
		if not self.webhook_url:
			raise ValueError('Webhook URL not configured')

		# 解析自定义headers
		try:
			custom_headers = json.loads(self.webhook_headers)
		except json.JSONDecodeError:
			custom_headers = {}
		
		# 构建请求数据
		data = {'title': title, 'content': content, 'timestamp': os.environ.get('GITHUB_RUN_ID', '')}
		payload = json.dumps({'message': data})
		
		# 构建请求头
		headers = {
			'Content-Type': 'application/json',
			'User-Agent': 'AnyRouter-CheckIn/1.0.0'
		}
		headers.update(custom_headers)
		
		# 对敏感信息进行base64编码显示
		safe_url = base64.b64encode(self.webhook_url.encode()).decode()
		safe_headers = base64.b64encode(self.webhook_headers.encode()).decode()
		print(f'[DEBUG] webhook_url: {safe_url}')
		print(f'[DEBUG] webhook_headers: {safe_headers}')
		print(f'[DEBUG] payload size: {len(payload)} bytes')
		
		try:
			print(f'[DEBUG] Sending POST request to webhook...')
			
			# 发送请求
			response = requests.request("POST", self.webhook_url, headers=headers, data=payload)
			
			print(f'[DEBUG] Response status: {response.status_code} {response.reason}')
			print(f'[DEBUG] Response headers: {dict(response.headers)}')
			print(f'[DEBUG] Response content: {response.text[:500]}...' if len(response.text) > 500 else f'[DEBUG] Response content: {response.text}')
			
			# 检查响应状态
			if 200 <= response.status_code < 300:
				print('[DEBUG] Webhook request completed successfully')
			else:
				print(f'[WARNING] Webhook returned non-2xx status: {response.status_code} {response.reason}')
			
		except requests.exceptions.ConnectTimeout as e:
			print(f'[ERROR] Webhook connection timeout: {e}')
			raise
		except requests.exceptions.ConnectionError as e:
			print(f'[ERROR] Webhook connection error: {e}')
			raise
		except requests.exceptions.Timeout as e:
			print(f'[ERROR] Webhook request timeout: {e}')
			raise
		except requests.exceptions.RequestException as e:
			print(f'[ERROR] Webhook request error: {e}')
			raise
		except Exception as e:
			print(f'[ERROR] Unexpected webhook error: {e}')
			raise

	def push_message(self, title: str, content: str, msg_type: Literal['text', 'html'] = 'text'):
		notifications = [
			('Email', lambda: self.send_email(title, content, msg_type)),
			('PushPlus', lambda: self.send_pushplus(title, content)),
			('Server Push', lambda: self.send_serverPush(title, content)),
			('DingTalk', lambda: self.send_dingtalk(title, content)),
			('Feishu', lambda: self.send_feishu(title, content)),
			('WeChat Work', lambda: self.send_wecom(title, content)),
			('Webhook', lambda: self.send_webhook(title, content)),
		]

		for name, func in notifications:
			try:
				func()
				print(f'[{name}]: Message push successful!')
			except Exception as e:
				print(f'[{name}]: Message push failed! Reason: {str(e)}')


notify = NotificationKit()
