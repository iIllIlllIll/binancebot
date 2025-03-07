import discord
from discord.ext import commands
import requests
from bs4 import BeautifulSoup
import time
from datetime import datetime, timezone
from binance.client import Client
from binance.enums import *
import matplotlib
matplotlib.use('Agg')  # 서버 환경에서 GUI 없이 사용
import sqlite3
import mplfinance as mpf
import pandas as pd
import tempfile
import os
import base64
import json
from openai import OpenAI
import numpy as np
from google import genai
import math
import colorama
from colorama import Fore, Style
from bs4 import BeautifulSoup
import pytz
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC




colorama.init(autoreset=True)

key_file_path = "keys.json"




# JSON 파일 읽기
with open(key_file_path, "r") as file:
    data = json.load(file)

# Intents 설정
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='#', intents=intents)

# 변수에 접근
api_key = data["api_key"]
api_secret = data["api_secret"]
openai_api_key = data['openai_api_key']
TOKEN = data['TOKEN']
webhook_url = data['webhook_url']
webhook_url_alert = data['webhook_url_alert']
webhook_url_data = data['webhook_url_data']

GEMINI_API_KEY = data["GEMINI_API_KEY"]

# Gemini API 설정
geminaiclient = genai.Client(api_key=GEMINI_API_KEY)


client = Client(api_key, api_secret)
openaiclient = OpenAI(api_key=openai_api_key)

with open("msg_system.txt", "r",encoding="utf-8") as file:
    msg_system_orig = file.read()
with open("msg_system_spike.txt","r",encoding="utf-8") as file:
    msg_system_spike_orig = file.read()




def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

MAX_ORDER_AGE = 180 # 오래된 주문 기준 시간 (초)
def cancel_old_orders(client: Client, symbol: str):
    global waiting, MAX_ORDER_AGE
    """
    활성화된 오래된 주문 취소 함수
    """
    try:
        # 활성화된 주문 목록 조회
        open_orders = client.futures_get_open_orders(symbol=symbol)
        now_timestamp = datetime.now(timezone.utc)  # 타임존 인식 객체로 변경

        if open_orders == []:
            waiting = False
        else:
            for order in open_orders:
                order_id = order['orderId']
                order_time = datetime.fromtimestamp(order['time'] / 1000, timezone.utc)  # UTC 타임존 설정

                # 오래된 주문 확인
                if (now_timestamp - order_time).total_seconds() > MAX_ORDER_AGE:
                    # 오래된 주문 취소
                    client.futures_cancel_order(symbol=symbol, orderId=order_id)
                    print(f"오래된 주문 취소: 주문 ID {order_id}, 생성 시간: {order_time}")
                    message(f"오래된 주문 취소: 주문 ID {order_id}, 생성 시간: {order_time}")

    except Exception as e:
        print(f"오래된 주문 취소 중 오류 발생: {e}")
        message(f"오래된 주문 취소 중 오류 발생: {e}")

DB_PATH = "data.db"


def create_tendency_chart(candles, position_list=None, candle_size=None):
    # 캔들 데이터 준비
    ohlc_data = {
        'Date': [datetime.fromtimestamp(candle[0] / 1000) for candle in candles],
        'Open': [float(candle[1]) for candle in candles],
        'High': [float(candle[2]) for candle in candles],
        'Low': [float(candle[3]) for candle in candles],
        'Close': [float(candle[4]) for candle in candles],
        'Volume': [float(candle[5]) for candle in candles],
    }
    
    df = pd.DataFrame(ohlc_data)
    df.set_index('Date', inplace=True)
    
    if df.empty:
        raise ValueError("DataFrame이 비어 있습니다. candles 데이터가 있는지 확인하세요.")
    
    # 스타일 설정
    mpf_style = mpf.make_mpf_style(
        base_mpf_style='charles',
        y_on_right=False,
        rc={'figure.figsize': (12, 8), 'axes.grid': True}
    )
    
    # addplot 리스트 초기화
    addplots = []
    
    if position_list is not None:
        # position_list 구조: [side, [buydate, ...], selldate]
        side = position_list[0].lower()  # 'long' 또는 'short'
        buy_dates_raw = position_list[1]  # 매수일 리스트
        sell_date_raw = position_list[2]   # 매도일
        
        def to_datetime(x):
            if isinstance(x, datetime):
                return x
            fmts = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"]
            for fmt in fmts:
                try:
                    return datetime.strptime(x, fmt)
                except ValueError:
                    pass
            return datetime.strptime(x, "%Y-%m-%d")
        
        buy_dates = [to_datetime(dt) for dt in buy_dates_raw]
        sell_date = to_datetime(sell_date_raw)
        
        # 매수/매도 시그널용 시리즈 (NaN으로 초기화)
        buy_marker_series = pd.Series(np.nan, index=df.index)
        sell_marker_series = pd.Series(np.nan, index=df.index)
        
        # 캔들 인덱스에서 가장 가까운 시각을 찾는 함수
        def get_nearest_index(target_dt):
            diffs = abs(df.index - target_dt)
            nearest_idx = diffs.argmin()
            return df.index[nearest_idx]
        
        # 매수 시그널 처리: 각 매수 시간에 대해 가장 가까운 봉에 표시
        for bdate in buy_dates:
            nearest_idx = get_nearest_index(bdate)
            row = df.loc[nearest_idx]
            offset = 0.02 * (row['High'] - row['Low'])
            if side == 'long':
                buy_marker_series[nearest_idx] = row['Low'] - offset
            elif side == 'short':
                buy_marker_series[nearest_idx] = row['High'] + offset
        
        # 매도 시그널 처리: sell_date에 대해 가장 가까운 봉에 표시
        nearest_sell_idx = get_nearest_index(sell_date)
        row = df.loc[nearest_sell_idx]
        offset = 0.02 * (row['High'] - row['Low'])
        if side == 'long':
            sell_marker_series[nearest_sell_idx] = row['High'] + offset
        elif side == 'short':
            sell_marker_series[nearest_sell_idx] = row['Low'] - offset
        
        # 실제 값이 존재하는 경우에만 addplot 추가
        if side == 'long':
            if buy_marker_series.notna().any():
                ap_buy = mpf.make_addplot(
                    buy_marker_series,
                    type='scatter',
                    markersize=100,
                    marker='^',
                    color='g'
                )
                addplots.append(ap_buy)
            if sell_marker_series.notna().any():
                ap_sell = mpf.make_addplot(
                    sell_marker_series,
                    type='scatter',
                    markersize=100,
                    marker='v',
                    color='r'
                )
                addplots.append(ap_sell)
        elif side == 'short':
            if buy_marker_series.notna().any():
                ap_buy = mpf.make_addplot(
                    buy_marker_series,
                    type='scatter',
                    markersize=100,
                    marker='v',
                    color='r'
                )
                addplots.append(ap_buy)
            if sell_marker_series.notna().any():
                ap_sell = mpf.make_addplot(
                    sell_marker_series,
                    type='scatter',
                    markersize=100,
                    marker='^',
                    color='g'
                )
                addplots.append(ap_sell)
    
    # 차트 제목 생성: 현재 날짜와 봉 크기 정보를 포함
    current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    side = side.upper() if position_list is not None else 'DATA'
    if candle_size:
        title = f"{side} : {current_time_str} - {candle_size} Candles Chart"
    else:
        title = f"{side} : {current_time_str} Candles Chart"
    
    # 차트 이미지 저장 경로 설정
    temp_dir = tempfile.gettempdir()
    file_path = os.path.join(temp_dir, "recent_5min_candles.png")
    
    # 차트 생성
    plot_kwargs = {
        "type": 'candle',
        "style": mpf_style,
        "volume": True,
        "ylabel": '',
        "ylabel_lower": '',
        "title": title,
        "savefig": dict(fname=file_path, dpi=100, bbox_inches='tight')
    }
    
    if addplots:
        plot_kwargs["addplot"] = addplots
    
    mpf.plot(df, **plot_kwargs)
    
    return file_path


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            side TEXT NOT NULL,
            result TEXT NOT NULL,
            leverage TEXT NOT NULL,
            pnl REAL NOT NULL,
            roi REAL NOT NULL,
            inv_amount REAL NOT NULL,
            count_value REAL NOT NULL,
            max_pnl REAL NOT NULL,
            min_pnl REAL NOT NULL,
            time TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()



# 데이터 저장 함수
def save_to_db(date, side, result, leverage, realized_profit, roi, inv_amount, count_value, max_pnl, min_pnl, time):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO data (date, side, result, leverage, pnl, roi, inv_amount, count_value, max_pnl, min_pnl, time) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (date, side, result, leverage, realized_profit, roi, inv_amount, count_value, max_pnl, min_pnl, time))
    conn.commit()
    conn.close()

def fetch_from_db(limit=None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    if limit:
        cursor.execute("SELECT date, side, result, leverage, pnl, roi, inv_amount, count_value, max_pnl, min_pnl, time FROM data ORDER BY id DESC LIMIT ?", (limit,))
    else:
        cursor.execute("SELECT date, side, result, leverage, pnl, roi, inv_amount, count_value, max_pnl, min_pnl, time FROM data ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()
    return rows





def get_candles(symbol, interval, candle_count):
    """
    symbol: 거래 심볼 (예: 'BTCUSDT')
    interval: 캔들 간격 (예: '5m', '15m', '1h' 등)
    candle_count: 반환받을 캔들 개수
    """
    # interval 단위에 따라 lookback 기간(분 단위)을 계산
    if interval.endswith('m'):
        unit = int(interval[:-1])  # 분 단위 (예: '5m' -> 5)
        total_minutes = candle_count * unit
        lookback = f"{total_minutes} minutes ago UTC"
    elif interval.endswith('h'):
        unit = int(interval[:-1])  # 시간 단위 (예: '1h' -> 1)
        total_minutes = candle_count * unit * 60
        lookback = f"{total_minutes} minutes ago UTC"
    else:
        raise ValueError("지원하지 않는 interval입니다. 예: '5m', '15m', '1h'")
    
    klines = client.get_historical_klines(symbol, interval, lookback)
    return klines[-candle_count:]

def required_candle_count(position_list, interval):
    """
    position_list: [side, [buydate, ...], selldate]
        - buydate와 selldate는 datetime 객체거나 문자열("YYYY-MM-DD HH:MM:SS" 또는 "YYYY-MM-DD HH:MM" 또는 "YYYY-MM-DD")로 제공됨
    interval: 캔들 간격 문자열 (예: '5m', '15m', '1h')
    
    반환: 차트에 포함되어야 할 총 봉 개수 (최초 매수 전 30봉 포함)
    """
    side = position_list[0].lower()
    raw_buydates = position_list[1]
    raw_selldate = position_list[2]
    
    # 문자열인 경우 datetime으로 변환하는 함수
    def to_datetime(x):
        if isinstance(x, datetime):
            return x
        fmts = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"]
        for fmt in fmts:
            try:
                return datetime.strptime(x, fmt)
            except ValueError:
                continue
        # 날짜만 있는 경우
        return datetime.strptime(x, "%Y-%m-%d")
    
    buy_dates = [to_datetime(dt) for dt in raw_buydates]
    sell_date = to_datetime(raw_selldate)
    
    # 매수일 중 가장 이른 시각
    earliest_buy = min(buy_dates)
    
    # sell_date가 earliest_buy보다 빠르면 오류 처리
    if sell_date < earliest_buy:
        raise ValueError("매도일(selldate)이 매수일(buydate)보다 빠를 수 없습니다.")
    
    # interval 문자열 파싱 (분 단위)
    if interval.endswith('m'):
        candle_interval = int(interval[:-1])
    elif interval.endswith('h'):
        candle_interval = int(interval[:-1]) * 60
    else:
        raise ValueError("지원하지 않는 interval입니다. 예: '5m', '15m', '1h'")
    
    # 매수일부터 매도일까지의 시간 차 (분)
    diff_minutes = (sell_date - earliest_buy).total_seconds() / 60.0
    
    # 매수부터 매도까지 몇 개의 봉이 필요한지 (봉 간격으로 나누고 올림)
    candles_between = math.ceil(diff_minutes / candle_interval) + 1  # 양 끝 포함
    
    # 매수 전 최소 30봉 추가
    total_required = 30 + candles_between
    return total_required



# 지갑 잔액 체크 함수 정의
def get_futures_asset_balance(symbol='USDT'):
    try:
        balance_info = client.futures_account_balance()
        for balance in balance_info:
            if balance['asset'] == symbol:
                return float(balance['availableBalance'])
        return 0.0
    except Exception as e:
        print(f"An error occurred: {e}")
        return 0.0

# 코인 잔액 체크 함수 정의
def get_asset_balance(symbol):
    try:
        positions = client.futures_position_information()
        for position in positions:
            if position['symbol'] == symbol:
                return float(position['isolatedMargin'])
        return None
    except Exception as e:
        print(f"An error occurred: {e}")
        return 0.0

# 레버리지 설정 함수 정의
def set_leverage(symbol, leverage):
    try:
        response = client.futures_change_leverage(symbol=symbol, leverage=leverage)
        print(f"Leverage set: {response}")
    except Exception as e:
        print(f"An error occurred while setting leverage: {e}")

def place_limit_order(symbol, price, quantity, leverage, side):
    # 레버리지 설정
    set_leverage(symbol, leverage)
    # 가격을 티크 사이즈에 맞게 반올림
    price = round_price_to_tick_size(symbol, price)
    try:
        order = client.futures_create_order(
            symbol=symbol,
            side=side,  # 'BUY' (롱) 또는 'SELL' (숏)
            type='LIMIT',
            timeInForce='GTC',  # Good Till Cancelled
            price=price,
            quantity=quantity
        )
        print(f"Order placed: {order}")
        return order
    except Exception as e:
        print(f"An error occurred: {e}")

def calculate_order_quantity(percentage):
    usdt_balance = get_futures_asset_balance()
    buy_quantity = usdt_balance * percentage / 100
    return round(buy_quantity, 3)

# 주문 실행 함수 : 종목, 지정가격, 퍼센트(자산), 레버리지, 주문 방향(side)
def execute_limit_order(symbol, price, percentage, leverage, side):  
    """
    :param symbol: 거래 종목
    :param price: 주문 가격
    :param percentage: 자산의 몇 퍼센트를 주문할 것인지
    :param leverage: 레버리지 값
    :param side: 주문 방향 ('BUY' : 롱, 'SELL' : 숏)
    """
    quantity = calculate_order_quantity(percentage)
    price = round_price_to_tick_size(symbol, price)
    if quantity > 0:
        # 주문 size 계산 : (자산의 금액 / 가격) * 레버리지
        size = round(quantity / price * leverage, 3)
        order = place_limit_order(symbol, price, size, leverage, side)
        return order
    else:
        print("Insufficient balance or invalid quantity.")

# close 함수 정의
def close(symbol):
    try:
        # 현재 오픈된 포지션 정보 가져오기
        positions = client.futures_position_information(symbol=symbol)
        for position in positions:
            if float(position['positionAmt']) != 0:
                # 포지션 청산
                side = 'SELL' if float(position['positionAmt']) > 0 else 'BUY'
                quantity = abs(float(position['positionAmt']))

                order = client.futures_create_order(
                    symbol=symbol,
                    side=side,
                    type='MARKET',
                    quantity=quantity,
                    reduceOnly=True
                )
                print(f"Position for {symbol} closed: {order}")
                return order
        print(f"No open position for {symbol}.")
    except Exception as e:
        print(f"An error occurred: {e}")

def close_usdt(symbol,leverage,usdt):
    try:
        # 현재 오픈된 포지션 정보 가져오기
        positions = client.futures_position_information(symbol=symbol)
        for position in positions:
            if float(position['positionAmt']) != 0:
                # 포지션 청산
                side = 'SELL' if float(position['positionAmt']) > 0 else 'BUY'
                entryprice = float(position['entryPrice'])  # 진입가격
                usdt = float(usdt)

                quantitytoclose = abs(float(usdt*leverage/entryprice))
                quantitytoclose = round(quantitytoclose,3)
                order = client.futures_create_order(
                    symbol=symbol,
                    side=side,
                    type='MARKET',
                    quantity=quantitytoclose,
                    reduceOnly=True
                )
                print(f"Position for {symbol} closed: {order}")
                return order
        print(f"No open position for {symbol}.")
    except Exception as e:
        print(f"An error occurred: {e}")




# 포지션 정보 가져오기 함수 정의
def get_futures_position_info(symbol):
    try:
        positions = client.futures_position_information()
        for position in positions:
            if position['symbol'] == symbol:
                return position
        return {
            'unRealizedProfit': 0,
            'positionAmt': 0,
            'entryPrice': 0,
            'liquidationPrice': 0
        }
    except Exception as e:
        print(f"An error occurred: {e}")
        return None
    



# 디코 웹훅 메세지 보내기 함수 정의
def message(message):
    data = {
        "content": message,
        "username": "Webhook Bot"  # Optional: 설정하지 않으면 기본 웹훅 이름이 사용됩니다.
    }

    result = requests.post(webhook_url, json=data)
    try:
        result.raise_for_status()
    except requests.exceptions.HTTPError as err:
        print(f"Error_msg: {err}")
    else:
        print(f"Payload delivered successfully, code {result.status_code}.")

def message_alert(message):
    data = {
        "content": message,
        "username": "Webhook Bot"  # Optional: 설정하지 않으면 기본 웹훅 이름이 사용됩니다.
    }

    result = requests.post(webhook_url_alert, json=data)
    try:
        result.raise_for_status()
    except requests.exceptions.HTTPError as err:
        print(f"Error: {err}")
    else:
        print(f"Payload delivered successfully, code {result.status_code}.")

def message_data(message, image_path=None):
    data = {
        "content": message,
        "username": "DATABASE"  # Optional: 지정하지 않으면 기본 웹훅 이름 사용
    }
    
    # image_path가 주어지면 multipart/form-data 방식으로 전송
    if image_path:
        with open(image_path, "rb") as f:
            files = {"file": f}
            payload = {"payload_json": json.dumps(data)}
            result = requests.post(webhook_url_data, data=payload, files=files)
    else:
        result = requests.post(webhook_url_data, json=data)
    
    try:
        result.raise_for_status()
    except requests.exceptions.HTTPError as err:
        print(f"Error: {err}")
    else:
        print(f"Payload delivered successfully, code {result.status_code}.")

# 주문 상태 확인 함수 정의
def check_order_status(symbol, order_id):
    try:
        order = client.futures_get_order(symbol=symbol, orderId=order_id)
        
        if order and order['status'] == 'FILLED':
            order = None

        return order
    except Exception as e:
        print(f"An error occurred: {e}")
        message(f"check_order_status : An error occurred: {e}")
        return None

# 틱 사이즈 확인 함수 정의
def get_tick_size(symbol):
    exchange_info = client.futures_exchange_info()
    for s in exchange_info['symbols']:
        if s['symbol'] == symbol:
            for f in s['filters']:
                if f['filterType'] == 'PRICE_FILTER':
                    return float(f['tickSize'])
    return None

# 틱 사이즈로 반올림 함수 정의
def round_price_to_tick_size(symbol,price):
    price = float(price)
    tick_size = get_tick_size(symbol)
    return round(price / tick_size) * tick_size

def get_latest_order(symbol):
    try:
        # 모든 주문 정보 가져오기
        orders = client.futures_get_all_orders(symbol=symbol, limit=10)

        # 주문이 없는 경우 처리
        if not orders:
            return None

        # 가장 최근 주문 정보 반환
        latest_order = orders[-1]
        return latest_order
    except Exception as e:
        print(f"An error occurred: {e}")
        return None
    

def openai_response(symbol,msg_system,msg_user,base64_image): # symbol, system 메세지, user메세지 입력
    try:
        response = openaiclient.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                "role": "system",
                "content": [
                    {
                    "type": "text",
                    "text": f"{msg_system}"
                    }
                ]
                },
                {
                "role": "user",
                "content": [
                    {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{base64_image}"
                    }
                    },
                    {
                    "type": "text",
                    "text": f"{msg_user}"
                    }
                ]
                }
            ],
            temperature=1,
            max_tokens=500,
            top_p=1,
            frequency_penalty=0,
            presence_penalty=0,
            response_format={
                "type": "json_object"
            }
            )
        return response
    except Exception as e:
        print(f"An error occurred: {e}")
        message(f"An error occurred: {e}")
        return None
    

def openai_response_msg(symbol,msg_system,msg_user): # symbol, system 메세지, user메세지 입력
    try:
        response = openaiclient.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                "role": "system",
                "content": [
                    {
                    "type": "text",
                    "text": f"{msg_system}"
                    }
                ]
                },
                {
                "role": "user",
                "content": [
                    {
                    "type": "text",
                    "text": f"{msg_user}"
                    }
                ]
                }
            ],
            temperature=1,
            top_p=1,
            frequency_penalty=0,
            presence_penalty=0,
            response_format={
                "type": "json_object"
            }
            )
        return response
    except Exception as e:
        print(f"An error occurred: {e}")
        message(f"An error occurred: {e}")
        return None


def openai_response_2(symbol,msg_system,msg_user,base64_image1,base64_image2): # symbol, system 메세지, user메세지 입력
    try:
        response = openaiclient.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                "role": "system",
                "content": [
                    {
                    "type": "text",
                    "text": f"{msg_system}"
                    }
                ]
                },
                {
                "role": "user",
                "content": [
                    {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{base64_image1}"
                    }
                    },
                    {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{base64_image2}"
                    }
                    },
                    {
                    "type": "text",
                    "text": f"{msg_user}"
                    }
                ]
                }
            ],
            temperature=0.5,
            max_tokens=700,
            top_p=1,
            frequency_penalty=0,
            presence_penalty=0,
            response_format={
                "type": "json_object"
            }
            )
        
        return response
    except Exception as e:
        print(f"An error occurred: {e}")
        message(f"An error occurred: {e}")
        return None
    
def check_spike(symbol,current_status):
    # 5분차트
    candles1 = get_candles(symbol, interval='5m', candle_count=200) 
    file_path1 = create_tendency_chart(candles1)
    base64_image1 = encode_image(file_path1)
    # 15분차트
    candles2 = get_candles(symbol, interval='15m', candle_count=150) 
    file_path2 = create_tendency_chart(candles2)
    base64_image2 = encode_image(file_path2)
    
    msg_stratagy_spike = msg_system_spike_orig
    msg_user_spike = "Now you have to do analysis with these chart data" + current_status
    response = openai_response_2(symbol,msg_stratagy_spike,msg_user_spike,base64_image1,base64_image2)

    ai_response = json.loads(response.choices[0].message.content)
    long_response = ai_response.get("long")
    short_response = ai_response.get("short")

    return long_response, short_response

def get_klines(symbol,interval='5m',limit=3):
    # [0] Open time, [1] Open, [2] High, [3] Low, [4] Close, [5] Volume,
    # [6] Close time, [7] Quote asset volume, [8] Number of trades, 
    # [9] Taker buy base asset volume, [10] Taker buy quote asset volume, [11] Ignore
    klines = client.get_klines(symbol=symbol, interval=interval, limit=limit)

    return klines

def is_good_to_buy(symbol,side):
    klines = get_klines(symbol,'5m',3)
    k3 = klines[2]
    k2 = klines[1]
    k1 = klines[0] # 가장 최근 봉

    if side == 'long':
        if k1[1] < k1[4] and k2[1] > k2[4] and k3[1] > k3[4]: # + - -
            return True
    elif side == 'short':
        if k1[1] > k1[4] and k2[1] < k2[4] and k3[1] < k3[4]: # - + +
            return True


def parse_date_range(date_range_text):
    """
    날짜 범위 문자열을 여러 포맷으로 시도하여 시작일과 종료일을 반환합니다.
    예: "2025-03-09 - 2025-03-15" 또는 "2025/03/09 - 2025/03/15"
    """
    start_str, end_str = date_range_text.split(" - ")
    for fmt in ("%Y/%m/%d", "%Y-%m-%d"):
        try:
            start_date = datetime.strptime(start_str, fmt).date()
            end_date = datetime.strptime(end_str, fmt).date()
            return start_date, end_date
        except Exception:
            continue
    raise ValueError(f"날짜 범위 파싱 실패: {date_range_text}")

def hide_logo_and_click_this_week(driver, wait):
    """
    로고 요소를 숨기고, '이번 주' 탭을 스크롤로 노출한 후 JavaScript로 직접 클릭합니다.
    """
    try:
        logo = driver.find_element(By.CSS_SELECTOR, ".investingLogo")
        driver.execute_script("arguments[0].style.display='none';", logo)
        print("로고 숨기기 완료")
    except Exception as e:
        print("로고 숨기기 실패:", e)
    
    time.sleep(1)
    
    try:
        this_week_tab = driver.find_element(By.ID, "timeFrame_thisWeek")
        driver.execute_script("arguments[0].scrollIntoView(true);", this_week_tab)
        time.sleep(1)
        driver.execute_script("arguments[0].click();", this_week_tab)
        print("이번 주 탭 클릭 완료 (JS)")
    except Exception as e:
        print("이번 주 탭 클릭 실패:", e)

def get_importance3_this_week_events():
    url = "https://kr.investing.com/economic-calendar/"
    
    # Selenium 옵션 설정
    options = Options()
    # 디버깅 시 headless 모드 주석 처리 (실제 창 확인)
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--lang=ko-KR")
    options.add_argument("user-agent=Mozilla/5.0 (X11; Linux x86_64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/115.0.0.0 Safari/537.36")
    
    # 크롬드라이버 경로 설정 (chromedriver.exe 경로)
    service = Service("./chromedriver-linux64/chromedriver")
    driver = webdriver.Chrome(service=service, options=options)
    
    try:
        driver.maximize_window()
        driver.get(url)
        print("페이지 요청 완료")
        message("페이지 요청 완료")

        wait = WebDriverWait(driver, 20)
        wait.until(EC.presence_of_element_located((By.ID, "economicCalendarData")))
        print("경제 캘린더 테이블 로드 완료")
        message("경제 캘린더 테이블 로드 완료")
        time.sleep(2)
        
        # 1. 필터 버튼 클릭
        try:
            filter_btn = driver.find_element(By.ID, "filterStateAnchor")
            filter_btn.click()
            print("필터 버튼 클릭")
            message("필터 버튼 클릭")
        except Exception as e:
            print("필터 버튼 클릭 실패:", e)
            message("필터 버튼 클릭 실패:", e)
        time.sleep(2)
        
        # 2. 중요도 체크박스 설정 (importance1, importance2 해제, importance3 체크)
        try:
            imp1 = driver.find_element(By.ID, "importance1")
            imp2 = driver.find_element(By.ID, "importance2")
            imp3 = driver.find_element(By.ID, "importance3")
            
            if imp1.is_selected():
                imp1.click()
            if imp2.is_selected():
                imp2.click()
            if not imp3.is_selected():
                imp3.click()
            print("중요도 3만 선택 완료")
            message("중요도 3만 선택 완료")
        except Exception as e:
            print("중요도 체크박스 설정 실패:", e)
            message("중요도 체크박스 설정 실패:", e)
        
        time.sleep(1)
        
        # 3. 필터 적용 버튼 클릭
        try:
            apply_btn = driver.find_element(By.ID, "ecSubmitButton")
            apply_btn.click()
            print("필터 적용 완료")
            message("필터 적용 완료")
        except Exception as e:
            print("필터 적용 실패:", e)
            message("필터 적용 실패:", e)
        time.sleep(3)
        
        # 4. '이번 주' 탭 클릭 (로고 숨기기 후 JS 클릭)
        hide_logo_and_click_this_week(driver, wait)
        time.sleep(3)
        
        # 페이지 소스 가져오기
        html = driver.page_source
    except Exception as e:
        print("Selenium 페이지 로드 오류:", e)
        message("Selenium 페이지 로드 오류:", e)
        driver.quit()
        return []
    finally:
        driver.quit()
    
    # BeautifulSoup으로 파싱
    soup = BeautifulSoup(html, "html.parser")
    
    # "이번 주" 날짜 범위 추출 (예: "2025-03-09 - 2025-03-15")
    date_range_div = soup.find("div", id="widgetFieldDateRange")
    if not date_range_div:
        print("날짜 범위 정보를 찾을 수 없습니다.")
        message("날짜 범위 정보를 찾을 수 없습니다.")
        return []
    
    date_range_text = date_range_div.get_text(strip=True)
    try:
        start_date, end_date = parse_date_range(date_range_text)
    except Exception as e:
        print("날짜 범위 파싱 오류:", e)
        message("날짜 범위 파싱 오류:", e)
        return []
    
    table = soup.find("table", id="economicCalendarData")
    if not table:
        print("경제 캘린더 테이블을 찾을 수 없습니다.")
        message("경제 캘린더 테이블을 찾을 수 없습니다.")
        return []
    
    events = []
    tbody = table.find("tbody")
    if not tbody:
        print("tbody를 찾을 수 없습니다.")
        message("tbody를 찾을 수 없습니다.")
        return events
    
    # 시간대 설정: data-event-datetime (미국 동부 시간 기준) → KST 변환
    eastern = pytz.timezone("America/New_York")
    kst = pytz.timezone("Asia/Seoul")
    
    for row in tbody.find_all("tr"):
        dt_attr = row.get("data-event-datetime")
        if not dt_attr:
            continue
        
        try:
            naive_dt = datetime.strptime(dt_attr, "%Y/%m/%d %H:%M:%S")
            eastern_dt = eastern.localize(naive_dt)
            kst_dt = eastern_dt.astimezone(kst)
        except Exception as e:
            print("날짜 변환 오류:", dt_attr, e)
            message("날짜 변환 오류:", dt_attr, e)
            continue
        
        if not (start_date <= kst_dt.date() <= end_date):
            continue
        
        tds = row.find_all("td")
        if not tds or len(tds) < 4:
            continue
        
        if len(tds) == 4:
            time_text = tds[0].get_text(strip=True)
            cur_val = tds[1].get_text(strip=True)
            event_val = tds[3].get_text(strip=True)
            actual_val = ""
            forecast_val = ""
            previous_val = ""
        elif len(tds) >= 7:
            time_text = tds[0].get_text(strip=True)
            cur_val = tds[1].get_text(strip=True)
            event_val = tds[3].get_text(strip=True)
            actual_val = tds[4].get_text(strip=True)
            forecast_val = tds[5].get_text(strip=True)
            previous_val = tds[6].get_text(strip=True)
        else:
            continue
        
        events.append({
            "Datetime": kst_dt.isoformat(),  # ISO 포맷 문자열로 저장
            "Time": time_text,
            "Currency": cur_val,
            "Event": event_val,
            "Actual": actual_val,
            "Forecast": forecast_val,
            "Previous": previous_val
        })
    
    return events




