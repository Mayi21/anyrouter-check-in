#!/usr/bin/env python3
"""
AnyRouter.top 自动签到脚本
"""

import asyncio
import hashlib
import json
import os
import sys
from datetime import datetime

import httpx
from dotenv import load_dotenv
from playwright.async_api import async_playwright

from utils.config import AccountConfig, AppConfig, load_accounts_config
from utils.notify import notify

load_dotenv()

BALANCE_HASH_FILE = 'balance_hash.txt'


def load_balance_hash():
	"""加载余额hash"""
	try:
		if os.path.exists(BALANCE_HASH_FILE):
			with open(BALANCE_HASH_FILE, 'r', encoding='utf-8') as f:
				return f.read().strip()
	except Exception:
		pass
	return None


def save_balance_hash(balance_hash):
	"""保存余额hash"""
	try:
		with open(BALANCE_HASH_FILE, 'w', encoding='utf-8') as f:
			f.write(balance_hash)
	except Exception as e:
		print(f'Warning: Failed to save balance hash: {e}')


def generate_balance_hash(balances):
	"""生成余额数据的hash"""
	# 将包含 quota 和 used 的结构转换为简单的 quota 值用于 hash 计算
	simple_balances = {k: v['quota'] for k, v in balances.items()} if balances else {}
	balance_json = json.dumps(simple_balances, sort_keys=True, separators=(',', ':'))
	return hashlib.sha256(balance_json.encode('utf-8')).hexdigest()[:16]


def load_jiubanai_accounts():
	"""从环境变量加载 jiubanai 账号配置"""
	accounts_str = os.getenv('JIUBANAI_ACCOUNTS')
	if not accounts_str:
		return None

	try:
		accounts_data = json.loads(accounts_str)

		# 检查是否为数组格式
		if not isinstance(accounts_data, list):
			print('ERROR: jiubanai account configuration must use array format [{}]')
			return None

		# 验证账号数据格式
		for i, account in enumerate(accounts_data):
			if not isinstance(account, dict):
				print(f'ERROR: jiubanai Account {i + 1} configuration format is incorrect')
				return None
			if 'cookies' not in account or 'veloera_user' not in account:
				print(f'ERROR: jiubanai Account {i + 1} missing required fields (cookies, veloera_user)')
				return None

		return accounts_data
	except Exception as e:
		print(f'ERROR: jiubanai account configuration format is incorrect: {e}')
		return None


def load_baozi_accounts():
	"""从环境变量加载 baozi 账号配置"""
	accounts_str = os.getenv('BAOZI_ACCOUNTS')
	if not accounts_str:
		return None

	try:
		accounts_data = json.loads(accounts_str)

		# 检查是否为数组格式
		if not isinstance(accounts_data, list):
			print('ERROR: baozi account configuration must use array format [{}]')
			return None

		# 验证账号数据格式
		for i, account in enumerate(accounts_data):
			if not isinstance(account, dict):
				print(f'ERROR: baozi Account {i + 1} configuration format is incorrect')
				return None
			if 'cookies' not in account:
				print(f'ERROR: baozi Account {i + 1} missing required field (cookies)')
				return None

		return accounts_data
	except Exception as e:
		print(f'ERROR: baozi account configuration format is incorrect: {e}')
		return None


def parse_cookies(cookies_data):
	"""解析 cookies 数据"""
	if isinstance(cookies_data, dict):
		return cookies_data

	if isinstance(cookies_data, str):
		cookies_dict = {}
		for cookie in cookies_data.split(';'):
			if '=' in cookie:
				key, value = cookie.strip().split('=', 1)
				cookies_dict[key] = value
		return cookies_dict
	return {}


async def get_waf_cookies_with_playwright(account_name: str, login_url: str):
	"""使用 Playwright 获取 WAF cookies（隐私模式）"""
	print(f'[PROCESSING] {account_name}: Starting browser to get WAF cookies...')

	async with async_playwright() as p:
		import tempfile

		with tempfile.TemporaryDirectory() as temp_dir:
			context = await p.chromium.launch_persistent_context(
				user_data_dir=temp_dir,
				headless=False,
				user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
				viewport={'width': 1920, 'height': 1080},
				args=[
					'--disable-blink-features=AutomationControlled',
					'--disable-dev-shm-usage',
					'--disable-web-security',
					'--disable-features=VizDisplayCompositor',
					'--no-sandbox',
				],
			)

			page = await context.new_page()

			try:
				print(f'[PROCESSING] {account_name}: Access login page to get initial cookies...')

				await page.goto(login_url, wait_until='networkidle')

				try:
					await page.wait_for_function('document.readyState === "complete"', timeout=5000)
				except Exception:
					await page.wait_for_timeout(3000)

				cookies = await page.context.cookies()

				waf_cookies = {}
				for cookie in cookies:
					cookie_name = cookie.get('name')
					cookie_value = cookie.get('value')
					if cookie_name in ['acw_tc', 'cdn_sec_tc', 'acw_sc__v2'] and cookie_value is not None:
						waf_cookies[cookie_name] = cookie_value

				print(f'[INFO] {account_name}: Got {len(waf_cookies)} WAF cookies')

				required_cookies = ['acw_tc', 'cdn_sec_tc', 'acw_sc__v2']
				missing_cookies = [c for c in required_cookies if c not in waf_cookies]

				if missing_cookies:
					print(f'[FAILED] {account_name}: Missing WAF cookies: {missing_cookies}')
					await context.close()
					return None

				print(f'[SUCCESS] {account_name}: Successfully got all WAF cookies')

				await context.close()

				return waf_cookies

			except Exception as e:
				print(f'[FAILED] {account_name}: Error occurred while getting WAF cookies: {e}')
				await context.close()
				return None


def get_user_info(client, headers, user_info_url: str):
	"""获取用户信息"""
	try:
		response = client.get(user_info_url, headers=headers, timeout=30)

		if response.status_code == 200:
			data = response.json()
			if data.get('success'):
				user_data = data.get('data', {})
				quota = round(user_data.get('quota', 0) / 500000, 2)
				used_quota = round(user_data.get('used_quota', 0) / 500000, 2)
				return {
					'success': True,
					'quota': quota,
					'used_quota': used_quota,
					'display': f':money: Current balance: ${quota}, Used: ${used_quota}',
				}
		return {'success': False, 'error': f'Failed to get user info: HTTP {response.status_code}'}
	except Exception as e:
		return {'success': False, 'error': f'Failed to get user info: {str(e)[:50]}...'}


async def prepare_cookies(account_name: str, provider_config, user_cookies: dict) -> dict | None:
	"""准备请求所需的 cookies（可能包含 WAF cookies）"""
	waf_cookies = {}

	if provider_config.needs_waf_cookies():
		login_url = f'{provider_config.domain}{provider_config.login_path}'
		waf_cookies = await get_waf_cookies_with_playwright(account_name, login_url)
		if not waf_cookies:
			print(f'[FAILED] {account_name}: Unable to get WAF cookies')
			return None
	else:
		print(f'[INFO] {account_name}: Bypass WAF not required, using user cookies directly')

	return {**waf_cookies, **user_cookies}


def execute_check_in(client, account_name: str, provider_config, headers: dict):
	"""执行签到请求"""
	print(f'[NETWORK] {account_name}: Executing check-in')

	checkin_headers = headers.copy()
	checkin_headers.update({'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest'})

	sign_in_url = f'{provider_config.domain}{provider_config.sign_in_path}'
	response = client.post(sign_in_url, headers=checkin_headers, timeout=30)

	print(f'[RESPONSE] {account_name}: Response status code {response.status_code}')

	if response.status_code == 200:
		try:
			result = response.json()
			if result.get('ret') == 1 or result.get('code') == 0 or result.get('success'):
				print(f'[SUCCESS] {account_name}: Check-in successful!')
				return True
			else:
				error_msg = result.get('msg', result.get('message', 'Unknown error'))
				print(f'[FAILED] {account_name}: Check-in failed - {error_msg}')
				return False
		except json.JSONDecodeError:
			# 如果不是 JSON 响应，检查是否包含成功标识
			if 'success' in response.text.lower():
				print(f'[SUCCESS] {account_name}: Check-in successful!')
				return True
			else:
				print(f'[FAILED] {account_name}: Check-in failed - Invalid response format')
				return False
	else:
		print(f'[FAILED] {account_name}: Check-in failed - HTTP {response.status_code}')
		return False


async def check_in_account(account: AccountConfig, account_index: int, app_config: AppConfig):
	"""为单个账号执行签到操作"""
	account_name = account.get_display_name(account_index)
	print(f'\n[PROCESSING] Starting to process {account_name}')

	provider_config = app_config.get_provider(account.provider)
	if not provider_config:
		print(f'[FAILED] {account_name}: Provider "{account.provider}" not found in configuration')
		return False, None

	print(f'[INFO] {account_name}: Using provider "{account.provider}" ({provider_config.domain})')

	user_cookies = parse_cookies(account.cookies)
	if not user_cookies:
		print(f'[FAILED] {account_name}: Invalid configuration format')
		return False, None

	all_cookies = await prepare_cookies(account_name, provider_config, user_cookies)
	if not all_cookies:
		return False, None

	client = httpx.Client(http2=True, timeout=30.0)

	try:
		client.cookies.update(all_cookies)

		headers = {
			'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
			'Accept': 'application/json, text/plain, */*',
			'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
			'Accept-Encoding': 'gzip, deflate, br, zstd',
			'Referer': provider_config.domain,
			'Origin': provider_config.domain,
			'Connection': 'keep-alive',
			'Sec-Fetch-Dest': 'empty',
			'Sec-Fetch-Mode': 'cors',
			'Sec-Fetch-Site': 'same-origin',
			provider_config.api_user_key: account.api_user,
		}

		user_info_url = f'{provider_config.domain}{provider_config.user_info_path}'
		user_info = get_user_info(client, headers, user_info_url)
		if user_info and user_info.get('success'):
			print(user_info['display'])
		elif user_info:
			print(user_info.get('error', 'Unknown error'))

		if provider_config.needs_manual_check_in():
			success = execute_check_in(client, account_name, provider_config, headers)
			return success, user_info
		else:
			print(f'[INFO] {account_name}: Check-in completed automatically (triggered by user info request)')
			return True, user_info

	except Exception as e:
		print(f'[FAILED] {account_name}: Error occurred during check-in process - {str(e)[:50]}...')
		return False, None
	finally:
		client.close()


def check_in_jiubanai_account(account_info, account_index):
	"""为单个 jiubanai 账号执行签到操作"""
	account_name = f'jiubanai Account {account_index + 1}'
	print(f'\n[PROCESSING] Starting to process {account_name}')

	# 解析账号配置
	cookies_data = account_info.get('cookies', {})
	veloera_user = account_info.get('veloera_user', '')

	if not veloera_user:
		print(f'[FAILED] {account_name}: veloera_user identifier not found')
		return False, 'veloera_user identifier not found'

	# 解析用户 cookies
	user_cookies = parse_cookies(cookies_data)
	if not user_cookies:
		print(f'[FAILED] {account_name}: Invalid configuration format')
		return False, 'Invalid configuration format'

	# 使用 httpx 进行 API 请求（jiubanai 无需 WAF 绕过）
	client = httpx.Client(http2=True, timeout=30.0)

	try:
		# 设置 cookies
		client.cookies.update(user_cookies)

		# 构建请求头
		headers = {
			'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
			'Accept': '*/*',
			'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
			'Accept-Encoding': 'gzip, deflate, br',
			'Referer': 'https://gy.jiubanai.com/app/me',
			'Host': 'gy.jiubanai.com',
			'Connection': 'keep-alive',
			'veloera-user': veloera_user,
		}

		print(f'[NETWORK] {account_name}: Executing check-in')

		response = client.post('https://gy.jiubanai.com/api/user/check_in', headers=headers, timeout=30)

		print(f'[RESPONSE] {account_name}: Response status code {response.status_code}')

		if response.status_code == 200:
			try:
				result = response.json()
				if result.get('success'):
					quota = result.get('data', {}).get('quota', 0)
					message = result.get('message', '签到成功')
					print(f'[SUCCESS] {account_name}: {message}')
					user_info_text = f'{message}\n💰 Quota gained: {quota}'
					return True, user_info_text
				else:
					error_msg = result.get('message', 'Unknown error')
					print(f'[FAILED] {account_name}: Check-in failed - {error_msg}')
					return False, error_msg
			except json.JSONDecodeError:
				error_msg = 'Invalid response format'
				print(f'[FAILED] {account_name}: {error_msg}')
				return False, error_msg
		else:
			error_msg = f'HTTP {response.status_code}'
			print(f'[FAILED] {account_name}: Check-in failed - {error_msg}')
			return False, error_msg

	except Exception as e:
		print(f'[FAILED] {account_name}: Error occurred during check-in process - {str(e)[:50]}...')
		return False, f'Error: {str(e)[:50]}'
	finally:
		client.close()


def check_in_baozi_account(account_info, account_index):
	"""为单个 baozi 账号执行签到操作"""
	account_name = account_info.get('name', f'baozi Account {account_index + 1}')
	print(f'\n[PROCESSING] Starting to process {account_name}')

	# 解析账号配置
	cookies_data = account_info.get('cookies', {})

	# 解析用户 cookies
	user_cookies = parse_cookies(cookies_data)
	if not user_cookies:
		print(f'[FAILED] {account_name}: Invalid configuration format')
		return False, 'Invalid configuration format'

	# 使用 httpx 进行 API 请求（baozi 无需 WAF 绕过）
	client = httpx.Client(http2=True, timeout=30.0)

	try:
		# 设置 cookies
		client.cookies.update(user_cookies)

		# 构建请求头
		headers = {
			'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
			'Accept': '*/*',
			'Host': 'lucky.5202030.xyz',
			'Connection': 'keep-alive',
		}

		print(f'[NETWORK] {account_name}: Executing check-in')

		response = client.post('https://lucky.5202030.xyz/lottery', headers=headers, timeout=30)

		print(f'[RESPONSE] {account_name}: Response status code {response.status_code}')

		if response.status_code == 200:
			try:
				result = response.json()
				success = result.get('success', False)
				message = result.get('message', '未知响应')

				if success:
					print(f'[SUCCESS] {account_name}: {message}')
					quota = result.get('quota', 0)
					current_balance = result.get('current_balance', 0)
					redemption_code = result.get('redemption_code', '')
					user_info_text = f'{message}\n💰 Quota: {quota}\n💵 Current balance: {current_balance}\n🎟️ Redemption code: {redemption_code}'
					return True, user_info_text
				# 如果不是 JSON 响应，检查是否包含成功标识
				if 'success' in response.text.lower():
					print(f'[INFO] {account_name}: Response success, checking balance changes...')

					# 获取签到后的余额信息
					user_info_after = get_user_info(client, headers)
					if user_info_after:
						print(f'[INFO] {account_name}: Balance after: {user_info_after["display_text"]}')

						# 比较余额是否有变化
						if user_info_before and user_info_after:
							balance_changed = user_info_after['quota'] != user_info_before['quota']
							if balance_changed:
								balance_diff = user_info_after['quota'] - user_info_before['quota']
								print(f'[SUCCESS] {account_name}: Check-in successful! Balance increased by ${balance_diff}')
								return True, {
									'before': user_info_before['display_text'],
									'after': user_info_after['display_text']
								}
							else:
								print(f'[SUCCESS] {account_name}: Response success but no balance change - likely already checked in today')
								return True, {
									'before': user_info_before['display_text'],
									'after': user_info_after['display_text']
								}
						else:
							print(f'[WARN] {account_name}: Unable to compare balance, treating as successful')
							return True, {
								'before': user_info_before['display_text'] if user_info_before else 'Unknown',
								'after': user_info_after['display_text'] if user_info_after else 'Unknown'
							}
					else:
						print(f'[WARN] {account_name}: Failed to get balance after check-in, treating as successful')
						return True, {
							'before': user_info_before['display_text'] if user_info_before else 'Unknown',
							'after': 'Unable to get balance'
						}
				else:
					print(f'[INFO] {account_name}: {message}')
					user_info_text = message
					return False, user_info_text
			except json.JSONDecodeError:
				error_msg = 'Invalid response format'
				print(f'[FAILED] {account_name}: {error_msg}')
				return False, error_msg
		else:
			error_msg = f'HTTP {response.status_code}'
			print(f'[FAILED] {account_name}: Check-in failed - {error_msg}')
			return False, error_msg

	except Exception as e:
		print(f'[FAILED] {account_name}: Error occurred during check-in process - {str(e)[:50]}...')
		return False, f'Error: {str(e)[:50]}'
	finally:
		client.close()


async def main():
	"""主函数"""
	print('[SYSTEM] Multi-site auto check-in script started')
	print(f'[TIME] Execution time: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')

	app_config = AppConfig.load_from_env()
	print(f'[INFO] Loaded {len(app_config.providers)} provider configuration(s)')

	# 加载 AnyRouter/AgentRouter 账号配置
	accounts = load_accounts_config()
	if not accounts:
		print('[WARNING] No AnyRouter/AgentRouter accounts configured')
		accounts = []

	if accounts:
		print(f'[INFO] Found {len(accounts)} AnyRouter/AgentRouter account configuration(s)')

	last_balance_hash = load_balance_hash()

	success_count = 0
	total_count = len(accounts)
	notification_content = []
	structured_results = []  # 新增：存储结构化的签到结果
	current_balances = {}
	need_notify = False  # 是否需要发送通知
	balance_changed = False  # 余额是否有变化

	# ========== 处理 AnyRouter/AgentRouter 账号 ==========
	for i, account in enumerate(accounts):
		account_key = f'account_{i + 1}'
		try:
			success, user_info = await check_in_account(account, i, app_config)
			if success:
				success_count += 1

			should_notify_this_account = False

			if not success:
				should_notify_this_account = True
				need_notify = True
				account_name = account.get_display_name(i)
				print(f'[NOTIFY] {account_name} failed, will send notification')

			if user_info and user_info.get('success'):
				current_quota = user_info['quota']
				current_used = user_info['used_quota']
				current_balances[account_key] = {'quota': current_quota, 'used': current_used}

			if should_notify_this_account:
				account_name = account.get_display_name(i)
				status = '[SUCCESS]' if success else '[FAIL]'
				account_result = f'{status} {account_name}'
				if user_info and user_info.get('success'):
					account_result += f'\n{user_info["display"]}'
				elif user_info:
					account_result += f'\n{user_info.get("error", "Unknown error")}'
				notification_content.append(account_result)

		except Exception as e:
			account_name = account.get_display_name(i)
			print(f'[FAILED] {account_name} processing exception: {e}')
			need_notify = True  # 异常也需要通知
			notification_content.append(f'[FAIL] {account_name} exception: {str(e)[:50]}...')

	# 检查余额变化
	current_balance_hash = generate_balance_hash(current_balances) if current_balances else None
	if current_balance_hash:
		if last_balance_hash is None:
			# 首次运行
			balance_changed = True
			need_notify = True
			print('[NOTIFY] First run detected, will send notification with current balances')
		elif current_balance_hash != last_balance_hash:
			# 余额有变化
			balance_changed = True
			need_notify = True
			print('[NOTIFY] Balance changes detected, will send notification')
		else:
			print('[INFO] No balance changes detected')

	# 为有余额变化的情况添加所有成功账号到通知内容
	if balance_changed:
		for i, account in enumerate(accounts):
			account_key = f'account_{i + 1}'
			if account_key in current_balances:
				account_name = account.get_display_name(i)
				# 只添加成功获取余额的账号，且避免重复添加
				account_result = f'[BALANCE] {account_name}'
				account_result += f'\n:money: Current balance: ${current_balances[account_key]["quota"]}, Used: ${current_balances[account_key]["used"]}'
				# 检查是否已经在通知内容中（避免重复）
				if not any(account_name in item for item in notification_content):
					notification_content.append(account_result)

	# 保存当前余额hash
	if current_balance_hash:
		save_balance_hash(current_balance_hash)

	# ========== jiubanai 签到 ==========
	print('\n' + '='*50)
	print('[SYSTEM] Starting jiubanai check-in process')
	print('='*50)

	jiubanai_accounts = load_jiubanai_accounts()
	jiubanai_success = 0
	jiubanai_total = 0
	jiubanai_notification_content = []

	if jiubanai_accounts:
		print(f'[INFO] Found {len(jiubanai_accounts)} jiubanai account configurations')
		jiubanai_total = len(jiubanai_accounts)

		for i, account in enumerate(jiubanai_accounts):
			try:
				success, user_info = check_in_jiubanai_account(account, i)
				if success:
					jiubanai_success += 1

				# jiubanai 总是需要通知（无论成功失败）
				need_notify = True
				status = '[SUCCESS]' if success else '[FAIL]'
				account_result = f'{status} jiubanai Account {i + 1}'
				if user_info:
					account_result += f'\n{user_info}'
				jiubanai_notification_content.append(account_result)
			except Exception as e:
				print(f'[FAILED] jiubanai Account {i + 1} processing exception: {e}')
				need_notify = True
				jiubanai_notification_content.append(f'[FAIL] jiubanai Account {i + 1} exception: {str(e)[:50]}...')
	else:
		print('[INFO] No jiubanai accounts configured, skipping')

	# ========== baozi 签到 ==========
	print('\n' + '='*50)
	print('[SYSTEM] Starting baozi check-in process')
	print('='*50)

	baozi_accounts = load_baozi_accounts()
	baozi_success = 0
	baozi_total = 0
	baozi_notification_content = []

	if baozi_accounts:
		print(f'[INFO] Found {len(baozi_accounts)} baozi account configurations')
		baozi_total = len(baozi_accounts)

		for i, account in enumerate(baozi_accounts):
			try:
				success, user_info = check_in_baozi_account(account, i)
				if success:
					baozi_success += 1

				# baozi 总是需要通知（无论成功失败）
				need_notify = True
				status = '[SUCCESS]' if success else '[INFO]'
				account_name = account.get('name', f'baozi Account {i + 1}')
				account_result = f'{status} {account_name}'
				if user_info:
					account_result += f'\n{user_info}'
				baozi_notification_content.append(account_result)
			except Exception as e:
				print(f'[FAILED] baozi Account {i + 1} processing exception: {e}')
				need_notify = True
				baozi_notification_content.append(f'[FAIL] baozi Account {i + 1} exception: {str(e)[:50]}...')
	else:
		print('[INFO] No baozi accounts configured, skipping')

	# ========== 构建最终通知内容 ==========
	if need_notify and (notification_content or jiubanai_notification_content or baozi_notification_content):
		time_info = f'[TIME] Execution time: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'

		final_notification = [time_info]

		# 添加 AnyRouter/AgentRouter 结果
		if notification_content:
			anyrouter_summary = [
				'',
				'=== AnyRouter/AgentRouter Check-in Results ===',
				'\n'.join(notification_content),
				f'[STATS] Success: {success_count}/{total_count}',
			]
			final_notification.extend(anyrouter_summary)

		# 添加 jiubanai 结果
		if jiubanai_notification_content:
			jiubanai_summary = [
				'',
				'=== jiubanai Check-in Results ===',
				'\n'.join(jiubanai_notification_content),
				f'[STATS] Success: {jiubanai_success}/{jiubanai_total}',
			]
			final_notification.extend(jiubanai_summary)

		# 添加 baozi 结果
		if baozi_notification_content:
			baozi_summary = [
				'',
				'=== baozi Check-in Results ===',
				'\n'.join(baozi_notification_content),
				f'[STATS] Success: {baozi_success}/{baozi_total}',
			]
			final_notification.extend(baozi_summary)

		# 总体统计
		total_all_success = success_count + jiubanai_success + baozi_success
		total_all_accounts = total_count + jiubanai_total + baozi_total

		if total_all_accounts > 0:
			overall_summary = []
			if total_all_success == total_all_accounts:
				overall_summary.append('\n[SUCCESS] All accounts check-in successful!')
			elif total_all_success > 0:
				overall_summary.append(f'\n[WARN] Partial success: {total_all_success}/{total_all_accounts}')
			else:
				overall_summary.append('\n[ERROR] All accounts check-in failed')
			final_notification.extend(overall_summary)

		notify_content = '\n'.join(final_notification)

		print('\n' + '='*50)
		print('[FINAL RESULTS]')
		print('='*50)
		print(notify_content)

		notify.push_message('Multi-Site Check-in Alert', notify_content, msg_type='text')
		print('[NOTIFY] Notification sent due to failures or balance changes')
	else:
		print('[INFO] All accounts successful and no balance changes detected, notification skipped')

	# 设置退出码
	total_all_success = success_count + jiubanai_success + baozi_success
	sys.exit(0 if total_all_success > 0 else 1)


def run_main():
	"""运行主函数的包装函数"""
	try:
		asyncio.run(main())
	except KeyboardInterrupt:
		print('\n[WARNING] Program interrupted by user')
		sys.exit(1)
	except Exception as e:
		print(f'\n[FAILED] Error occurred during program execution: {e}')
		sys.exit(1)


if __name__ == '__main__':
	run_main()
