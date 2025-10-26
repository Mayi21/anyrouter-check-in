#!/usr/bin/env python3
"""
AnyRouter.top 自动签到脚本
"""

import asyncio
import json
import os
import sys
from datetime import datetime

import httpx
from dotenv import load_dotenv
from playwright.async_api import async_playwright

from notify import notify

load_dotenv()


def load_accounts():
	"""从环境变量加载多账号配置"""
	accounts_str = os.getenv('ANYROUTER_ACCOUNTS')
	if not accounts_str:
		print('ERROR: ANYROUTER_ACCOUNTS environment variable not found')
		return None

	try:
		accounts_data = json.loads(accounts_str)

		# 检查是否为数组格式
		if not isinstance(accounts_data, list):
			print('ERROR: Account configuration must use array format [{}]')
			return None

		# 验证账号数据格式
		for i, account in enumerate(accounts_data):
			if not isinstance(account, dict):
				print(f'ERROR: Account {i + 1} configuration format is incorrect')
				return None
			if 'cookies' not in account or 'api_user' not in account:
				print(f'ERROR: Account {i + 1} missing required fields (cookies, api_user)')
				return None

		return accounts_data
	except Exception as e:
		print(f'ERROR: Account configuration format is incorrect: {e}')
		return None


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


async def get_waf_cookies_with_playwright(account_name: str):
	"""使用 Playwright 获取 WAF cookies（隐私模式）"""
	print(f'[PROCESSING] {account_name}: Starting browser to get WAF cookies...')

	async with async_playwright() as p:
		context = await p.chromium.launch_persistent_context(
			user_data_dir=None,
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
			print(f'[PROCESSING] {account_name}: Step 1: Access login page to get initial cookies...')

			await page.goto('https://anyrouter.top/login', wait_until='networkidle')

			try:
				await page.wait_for_function('document.readyState === "complete"', timeout=5000)
			except Exception:
				await page.wait_for_timeout(3000)

			cookies = await page.context.cookies()

			waf_cookies = {}
			for cookie in cookies:
				if cookie['name'] in ['acw_tc', 'cdn_sec_tc', 'acw_sc__v2']:
					waf_cookies[cookie['name']] = cookie['value']

			print(f'[INFO] {account_name}: Got {len(waf_cookies)} WAF cookies after step 1')

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


def get_user_info(client, headers):
	"""获取用户信息"""
	try:
		response = client.get('https://anyrouter.top/api/user/self', headers=headers, timeout=30)

		if response.status_code == 200:
			data = response.json()
			if data.get('success'):
				user_data = data.get('data', {})
				quota = round(user_data.get('quota', 0) / 500000, 2)
				used_quota = round(user_data.get('used_quota', 0) / 500000, 2)
				return f':money: Current balance: ${quota}, Used: ${used_quota}'
	except Exception as e:
		return f'[FAIL] Failed to get user info: {str(e)[:50]}...'
	return None


async def check_in_account(account_info, account_index):
	"""为单个账号执行签到操作"""
	account_name = f'Account {account_index + 1}'
	print(f'\n[PROCESSING] Starting to process {account_name}')

	# 解析账号配置
	cookies_data = account_info.get('cookies', {})
	api_user = account_info.get('api_user', '')

	if not api_user:
		print(f'[FAILED] {account_name}: API user identifier not found')
		return False, None

	# 解析用户 cookies
	user_cookies = parse_cookies(cookies_data)
	if not user_cookies:
		print(f'[FAILED] {account_name}: Invalid configuration format')
		return False, None

	# 步骤1：获取 WAF cookies
	waf_cookies = await get_waf_cookies_with_playwright(account_name)
	if not waf_cookies:
		print(f'[FAILED] {account_name}: Unable to get WAF cookies')
		return False, None

	# 步骤2：使用 httpx 进行 API 请求
	client = httpx.Client(http2=True, timeout=30.0)

	try:
		# 合并 WAF cookies 和用户 cookies
		all_cookies = {**waf_cookies, **user_cookies}
		client.cookies.update(all_cookies)

		headers = {
			'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
			'Accept': 'application/json, text/plain, */*',
			'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
			'Accept-Encoding': 'gzip, deflate, br, zstd',
			'Referer': 'https://anyrouter.top/console',
			'Origin': 'https://anyrouter.top',
			'Connection': 'keep-alive',
			'Sec-Fetch-Dest': 'empty',
			'Sec-Fetch-Mode': 'cors',
			'Sec-Fetch-Site': 'same-origin',
			'new-api-user': api_user,
		}

		user_info_text = None

		user_info = get_user_info(client, headers)
		if user_info:
			print(user_info)
			user_info_text = user_info

		print(f'[NETWORK] {account_name}: Executing check-in')

		# 更新签到请求头
		checkin_headers = headers.copy()
		checkin_headers.update({'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest'})

		response = client.post('https://anyrouter.top/api/user/sign_in', headers=checkin_headers, timeout=30)

		print(f'[RESPONSE] {account_name}: Response status code {response.status_code}')

		if response.status_code == 200:
			try:
				result = response.json()
				if result.get('ret') == 1 or result.get('code') == 0 or result.get('success'):
					print(f'[SUCCESS] {account_name}: Check-in successful!')
					return True, user_info_text
				else:
					error_msg = result.get('msg', result.get('message', 'Unknown error'))
					print(f'[FAILED] {account_name}: Check-in failed - {error_msg}')
					return False, user_info_text
			except json.JSONDecodeError:
				# 如果不是 JSON 响应，检查是否包含成功标识
				if 'success' in response.text.lower():
					print(f'[SUCCESS] {account_name}: Check-in successful!')
					return True, user_info_text
				else:
					print(f'[FAILED] {account_name}: Check-in failed - Invalid response format')
					return False, user_info_text
		else:
			print(f'[FAILED] {account_name}: Check-in failed - HTTP {response.status_code}')
			return False, user_info_text

	except Exception as e:
		print(f'[FAILED] {account_name}: Error occurred during check-in process - {str(e)[:50]}...')
		return False, user_info_text
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
		return False, None

	# 解析用户 cookies
	user_cookies = parse_cookies(cookies_data)
	if not user_cookies:
		print(f'[FAILED] {account_name}: Invalid configuration format')
		return False, None

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
					message = result.get('message', 'Check-in successful')
					print(f'[SUCCESS] {account_name}: {message}')
					user_info_text = f'💰 Quota gained: {quota}'
					return True, user_info_text
				else:
					error_msg = result.get('message', 'Unknown error')
					print(f'[FAILED] {account_name}: Check-in failed - {error_msg}')
					return False, None
			except json.JSONDecodeError:
				print(f'[FAILED] {account_name}: Check-in failed - Invalid response format')
				return False, None
		else:
			print(f'[FAILED] {account_name}: Check-in failed - HTTP {response.status_code}')
			return False, None

	except Exception as e:
		print(f'[FAILED] {account_name}: Error occurred during check-in process - {str(e)[:50]}...')
		return False, None
	finally:
		client.close()


async def main():
	"""主函数"""
	print('[SYSTEM] Multi-site auto check-in script started')
	print(f'[TIME] Execution time: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')

	time_info = f'[TIME] Execution time: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'
	all_results = []
	total_success = 0
	total_accounts = 0

	# ========== AnyRouter 签到 ==========
	print('\n' + '='*50)
	print('[SYSTEM] Starting AnyRouter check-in process')
	print('='*50)

	accounts = load_accounts()
	if accounts:
		print(f'[INFO] Found {len(accounts)} AnyRouter account configurations')

		anyrouter_results = []
		anyrouter_success = 0
		anyrouter_total = len(accounts)

		for i, account in enumerate(accounts):
			try:
				success, user_info = await check_in_account(account, i)
				if success:
					anyrouter_success += 1
				# 收集通知内容
				status = '[SUCCESS]' if success else '[FAIL]'
				account_result = f'{status} Account {i + 1}'
				if user_info:
					account_result += f'\n{user_info}'
				anyrouter_results.append(account_result)
			except Exception as e:
				print(f'[FAILED] Account {i + 1} processing exception: {e}')
				anyrouter_results.append(f'[FAIL] Account {i + 1} exception: {str(e)[:50]}...')

		# 构建 AnyRouter 结果
		anyrouter_summary = [
			'=== AnyRouter Check-in Results ===',
			'\n'.join(anyrouter_results),
			f'\n[STATS] Success: {anyrouter_success}/{anyrouter_total}',
		]
		all_results.append('\n'.join(anyrouter_summary))
		total_success += anyrouter_success
		total_accounts += anyrouter_total
	else:
		print('[INFO] No AnyRouter accounts configured, skipping')

	# ========== jiubanai 签到 ==========
	print('\n' + '='*50)
	print('[SYSTEM] Starting jiubanai check-in process')
	print('='*50)

	jiubanai_accounts = load_jiubanai_accounts()
	if jiubanai_accounts:
		print(f'[INFO] Found {len(jiubanai_accounts)} jiubanai account configurations')

		jiubanai_results = []
		jiubanai_success = 0
		jiubanai_total = len(jiubanai_accounts)

		for i, account in enumerate(jiubanai_accounts):
			try:
				success, user_info = check_in_jiubanai_account(account, i)
				if success:
					jiubanai_success += 1
				# 收集通知内容
				status = '[SUCCESS]' if success else '[FAIL]'
				account_result = f'{status} Account {i + 1}'
				if user_info:
					account_result += f'\n{user_info}'
				jiubanai_results.append(account_result)
			except Exception as e:
				print(f'[FAILED] jiubanai Account {i + 1} processing exception: {e}')
				jiubanai_results.append(f'[FAIL] Account {i + 1} exception: {str(e)[:50]}...')

		# 构建 jiubanai 结果
		jiubanai_summary = [
			'=== jiubanai Check-in Results ===',
			'\n'.join(jiubanai_results),
			f'\n[STATS] Success: {jiubanai_success}/{jiubanai_total}',
		]
		all_results.append('\n'.join(jiubanai_summary))
		total_success += jiubanai_success
		total_accounts += jiubanai_total
	else:
		print('[INFO] No jiubanai accounts configured, skipping')

	# ========== 总结 ==========
	if total_accounts == 0:
		print('[ERROR] No accounts configured for any site!')
		sys.exit(1)

	overall_summary = []
	if total_success == total_accounts:
		overall_summary.append('[SUCCESS] All accounts check-in successful!')
	elif total_success > 0:
		overall_summary.append(f'[WARN] Partial success: {total_success}/{total_accounts}')
	else:
		overall_summary.append('[ERROR] All accounts check-in failed')

	# 构建完整通知内容
	notify_content = '\n\n'.join([time_info] + all_results + overall_summary)

	print('\n' + '='*50)
	print('[FINAL RESULTS]')
	print('='*50)
	print(notify_content)

	notify.push_message('Multi-Site Check-in Results', notify_content, msg_type='text')

	# 设置退出码
	sys.exit(0 if total_success > 0 else 1)


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
