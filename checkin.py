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
				return {
					'quota': quota,
					'used_quota': used_quota,
					'display_text': f':money: Current balance: ${quota}, Used: ${used_quota}'
				}
	except Exception as e:
		return None
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
		return False, {
			'before': 'Configuration error',
			'after': 'API user not found'
		}

	# 解析用户 cookies
	user_cookies = parse_cookies(cookies_data)
	if not user_cookies:
		print(f'[FAILED] {account_name}: Invalid configuration format')
		return False, {
			'before': 'Configuration error',
			'after': 'Invalid cookies format'
		}

	# 步骤1：获取 WAF cookies
	waf_cookies = await get_waf_cookies_with_playwright(account_name)
	if not waf_cookies:
		print(f'[FAILED] {account_name}: Unable to get WAF cookies')
		return False, {
			'before': 'Unable to get balance',
			'after': 'WAF cookies failed'
		}

	# 步骤2：使用 httpx 进行 API 请求
	client = httpx.Client(http2=True, timeout=30.0)

	# 初始化变量
	user_info_before = None

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

		# 获取签到前的余额信息
		print(f'[INFO] {account_name}: Getting balance before check-in...')
		user_info_before = get_user_info(client, headers)
		if user_info_before:
			print(f'[INFO] {account_name}: Balance before: {user_info_before["display_text"]}')
		else:
			print(f'[WARN] {account_name}: Failed to get balance before check-in')

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
					print(f'[INFO] {account_name}: API returned success, checking balance changes...')
					
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
								print(f'[SUCCESS] {account_name}: API success but no balance change - likely already checked in today')
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
					error_msg = result.get('msg', result.get('message', 'Unknown error'))
					print(f'[FAILED] {account_name}: Check-in failed - {error_msg}')
					user_info_final = {
						'before': user_info_before['display_text'] if user_info_before else 'Unknown',
						'after': 'Check-in failed'
					}
					return False, user_info_final
			except json.JSONDecodeError:
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
					print(f'[FAILED] {account_name}: Check-in failed - Invalid response format')
					user_info_final = {
						'before': user_info_before['display_text'] if user_info_before else 'Unknown',
						'after': 'Invalid response format'
					}
					return False, user_info_final
		else:
			print(f'[FAILED] {account_name}: Check-in failed - HTTP {response.status_code}')
			user_info_final = {
				'before': user_info_before['display_text'] if user_info_before else 'Unknown',
				'after': f'HTTP {response.status_code} error'
			}
			return False, user_info_final

	except Exception as e:
		print(f'[FAILED] {account_name}: Error occurred during check-in process - {str(e)[:50]}...')
		user_info_final = {
			'before': user_info_before['display_text'] if user_info_before else 'Unknown',
			'after': f'Exception: {str(e)[:20]}...'
		}
		return False, user_info_final
	finally:
		client.close()


async def main():
	"""主函数"""
	print('[SYSTEM] AnyRouter.top multi-account auto check-in script started (using Playwright)')
	print(f'[TIME] Execution time: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')

	# 加载账号配置
	accounts = load_accounts()
	if not accounts:
		print('[FAILED] Unable to load account configuration, program exits')
		sys.exit(1)

	print(f'[INFO] Found {len(accounts)} account configurations')

	# 为每个账号执行签到
	success_count = 0
	total_count = len(accounts)
	notification_content = []
	structured_results = []  # 新增：存储结构化的签到结果

	for i, account in enumerate(accounts):
		try:
			success, balance_info = await check_in_account(account, i)
			if success:
				success_count += 1
			
			# 构建结构化结果数据
			account_result = {
				'account_index': i + 1,
				'success': success,
				'balance_before': None,
				'balance_after': None,
				'balance_before_raw': None,
				'balance_after_raw': None,
				'error_message': None
			}
			
			# 解析余额信息
			if balance_info and isinstance(balance_info, dict):
				if 'before' in balance_info and 'after' in balance_info:
					account_result['balance_before'] = balance_info['before']
					account_result['balance_after'] = balance_info['after']
					# 尝试提取原始数值
					try:
						# 从 display_text 中提取数值，格式如 ":money: Current balance: $5.0, Used: $2.5"
						before_text = balance_info['before']
						after_text = balance_info['after']
						
						if 'Current balance: $' in before_text:
							before_balance = float(before_text.split('Current balance: $')[1].split(',')[0])
							account_result['balance_before_raw'] = before_balance
						
						if 'Current balance: $' in after_text:
							after_balance = float(after_text.split('Current balance: $')[1].split(',')[0])
							account_result['balance_after_raw'] = after_balance
					except:
						pass
				else:
					account_result['error_message'] = str(balance_info)
			elif not success:
				account_result['error_message'] = balance_info if isinstance(balance_info, str) else 'Unknown error'
			
			structured_results.append(account_result)
			
			# 保持原有的文本格式（向后兼容）
			status = '[SUCCESS]' if success else '[FAIL]'
			account_text = f'{status} Account {i + 1}'
			if balance_info:
				if isinstance(balance_info, dict) and 'before' in balance_info and 'after' in balance_info:
					account_text += f'\nBefore: {balance_info["before"]}'
					account_text += f'\nAfter: {balance_info["after"]}'
				else:
					# 兼容旧格式
					account_text += f'\n{balance_info}'
			notification_content.append(account_text)
		except Exception as e:
			print(f'[FAILED] Account {i + 1} processing exception: {e}')
			notification_content.append(f'[FAIL] Account {i + 1} exception: {str(e)[:50]}...')
			structured_results.append({
				'account_index': i + 1,
				'success': False,
				'balance_before': None,
				'balance_after': None,
				'balance_before_raw': None,
				'balance_after_raw': None,
				'error_message': f'Exception: {str(e)[:50]}...'
			})

	# 构建通知内容
	summary = [
		'[STATS] Check-in result statistics:',
		f'[SUCCESS] Success: {success_count}/{total_count}',
		f'[FAIL] Failed: {total_count - success_count}/{total_count}',
	]

	if success_count == total_count:
		summary.append('[SUCCESS] All accounts check-in successful!')
	elif success_count > 0:
		summary.append('[WARN] Some accounts check-in successful')
	else:
		summary.append('[ERROR] All accounts check-in failed')

	time_info = f'[TIME] Execution time: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'

	notify_content = '\n\n'.join([time_info, '\n'.join(notification_content), '\n'.join(summary)])

	print(notify_content)

	# 发送通知，无论签到是否成功
	print(f'[NOTIFY] Sending notification for check-in results: {success_count}/{total_count} successful')
	
	# 构建完整的通知数据
	notification_data = {
		'title': 'AnyRouter Check-in Results',
		'content': notify_content,
		'summary': {
			'success_count': success_count,
			'total_count': total_count,
			'execution_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
		},
		'accounts': structured_results
	}
	
	notify.push_message_structured(notification_data, msg_type='text')

	# 设置退出码
	sys.exit(0 if success_count > 0 else 1)


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
