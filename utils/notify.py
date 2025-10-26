import base64
import json
import os
import smtplib
from email.mime.text import MIMEText
from typing import Literal

import httpx
import requests


class NotificationKit:
	def __init__(self):
		self.email_user: str = os.getenv('EMAIL_USER', '')
		self.email_pass: str = os.getenv('EMAIL_PASS', '')
		self.email_to: str = os.getenv('EMAIL_TO', '')
		self.smtp_server: str = os.getenv('CUSTOM_SMTP_SERVER', '')
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

		# MIMEText 需要 'plain' 或 'html'，而不是 'text'
		mime_subtype = 'plain' if msg_type == 'text' else 'html'
		msg = MIMEText(content, mime_subtype, 'utf-8')
		msg['From'] = f'AnyRouter Assistant <{self.email_user}>'
		msg['To'] = self.email_to
		msg['Subject'] = title

		smtp_server = self.smtp_server if self.smtp_server else f'smtp.{self.email_user.split("@")[1]}'
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

	def send_webhook(self, title: str, content: str, structured_data=None):
		if not self.webhook_url:
			raise ValueError('Webhook URL not configured')

		# 解析自定义headers
		try:
			custom_headers = json.loads(self.webhook_headers)
		except json.JSONDecodeError:
			custom_headers = {}
		
		# 增加支持对于telegram的特殊处理
		if "WEBHOOK_TYPE" in custom_headers and custom_headers["WEBHOOK_TYPE"].lower() == "telegram":
			if structured_data:
				# 为 Telegram Bot 构建 HTML 格式的消息
				html_content = self._format_telegram_html(structured_data)
				payload = json.dumps({
					"message": html_content
				})
			else:
				# fallback 到纯文本
				payload = json.dumps({
					"text": f"<b>{title}</b>\n\n{content}",
					"parse_mode": "HTML"
				})
		else:
			# 构建请求数据
			data = {'title': title, 'content': content, 'timestamp': os.environ.get('GITHUB_RUN_ID', '')}
			payload = json.dumps({
					"message": json.dumps(data, ensure_ascii=False)
					})
		

		
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

	def _format_telegram_html(self, structured_data):
		"""为 Telegram Bot 格式化 HTML 消息"""
		title = structured_data.get('title', 'Check-in Results')
		summary = structured_data.get('summary', {})
		accounts = structured_data.get('accounts', [])
		
		# 构建 HTML 消息
		html_parts = []
		
		# 标题
		html_parts.append(f"<b>🤖 {title}</b>")
		
		# 执行时间
		if 'execution_time' in summary:
			html_parts.append(f"⏰ <i>{summary['execution_time']}</i>")
		
		# 统计信息
		success_count = summary.get('success_count', 0)
		total_count = summary.get('total_count', 0)
		
		if success_count == total_count:
			status_emoji = "✅"
			status_text = "All Successful"
		elif success_count > 0:
			status_emoji = "⚠️"
			status_text = "Partially Successful"
		else:
			status_emoji = "❌"
			status_text = "All Failed"
		
		html_parts.append(f"\n{status_emoji} <b>Status:</b> {status_text}")
		html_parts.append(f"📊 <b>Results:</b> {success_count}/{total_count} accounts")
		
		# 账号详情
		if accounts:
			html_parts.append("\n<b>📋 Account Details:</b>")
			for account in accounts:
				account_num = account.get('account_index', 'Unknown')
				success = account.get('success', False)
				
				# 状态标识
				status_icon = "✅" if success else "❌"
				html_parts.append(f"\n{status_icon} <b>Account {account_num}</b>")
				
				# 余额信息
				if success and account.get('balance_before_raw') is not None and account.get('balance_after_raw') is not None:
					before_balance = account.get('balance_before_raw')
					after_balance = account.get('balance_after_raw')
					balance_diff = after_balance - before_balance
					
					if balance_diff > 0:
						html_parts.append(f"   💰 Balance: ${before_balance:.2f} → ${after_balance:.2f} <b>(+${balance_diff:.2f})</b>")
					else:
						html_parts.append(f"   💰 Balance: ${before_balance:.2f} (No change)")
				elif account.get('balance_before') and account.get('balance_after'):
					# fallback 到文本格式
					html_parts.append(f"   📝 Before: {account.get('balance_before')}")
					html_parts.append(f"   📝 After: {account.get('balance_after')}")
				
				# 错误信息
				if not success and account.get('error_message'):
					error_msg = account.get('error_message', 'Unknown error')
					html_parts.append(f"   ❌ Error: <code>{error_msg[:50]}{'...' if len(error_msg) > 50 else ''}</code>")
		
		return '\n'.join(html_parts)

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

	def push_message_structured(self, notification_data, msg_type: Literal['text', 'html'] = 'text'):
		"""发送结构化通知数据，支持 Telegram HTML 格式"""
		title = notification_data.get('title', 'Notification')
		content = notification_data.get('content', '')
		
		notifications = [
			('Email', lambda: self.send_email(title, content, msg_type)),
			('PushPlus', lambda: self.send_pushplus(title, content)),
			('Server Push', lambda: self.send_serverPush(title, content)),
			('DingTalk', lambda: self.send_dingtalk(title, content)),
			('Feishu', lambda: self.send_feishu(title, content)),
			('WeChat Work', lambda: self.send_wecom(title, content)),
			('Webhook', lambda: self.send_webhook(title, content, notification_data)),  # 传递结构化数据给 webhook
		]

		for name, func in notifications:
			try:
				func()
				print(f'[{name}]: Message push successful!')
			except Exception as e:
				print(f'[{name}]: Message push failed! Reason: {str(e)}')


notify = NotificationKit()
