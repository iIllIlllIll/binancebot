import discord
import time
from datetime import datetime
from binance.enums import *
import asyncio
import matplotlib
matplotlib.use('Agg')  # 서버 환경에서 GUI 없이 사용
import sqlite3
import mplfinance as mpf
import os
import traceback
import json
import sys
from functions import *

# 초기설정
initial_leverage = 20
leverage = 20
symbol = "BTCUSDT"
sell_price = 0  # 마지막 판매 가격
n = 2  # 100/2^n

date_diff_setting = 3

count = 0

target_pnl = 13
safe_pnl = 5
stoploss_pnl = 7
add_pnl = 7

# 전략 실행 상태
is_running = False
waiting = False
Aicommand = False  

current_side = None


# 최고 수익률 기록
max_pnl = 0
min_pnl = 0

# 일정 파일 저장 경로 (절대 경로 사용 권장)
SCHEDULE_FILE = os.path.join(os.getcwd(), "events.txt")
# 전역 변수에 로드한 일정 데이터 저장 (리로드 시 사용)
schedule_data = None







def load_schedule():
    """저장된 파일에서 일정 데이터를 로드합니다."""
    global schedule_data
    try:
        with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
            schedule_data = json.load(f)
        print(f"파일 로드 성공: {SCHEDULE_FILE}, 항목 수: {len(schedule_data)}")
    except Exception as e:
        print(f"파일 로드 실패: {e}")
        schedule_data = None

def save_schedule():
    """변경된 schedule_data를 파일에 저장합니다."""
    global schedule_data
    try:
        with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
            json.dump(schedule_data, f, ensure_ascii=False, indent=2)
        print("일정 데이터 저장 완료")
    except Exception as e:
        print(f"일정 데이터 저장 실패: {e}")

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

def extract_json(text):
    """
    응답 텍스트에서 코드 블록(```json ... ```) 내의 JSON 데이터를 추출합니다.
    코드 블록이 없으면, 첫 번째 '['와 마지막 ']' 사이의 문자열을 반환합니다.
    """
    import re
    pattern = re.compile(r"```json\s*(\[[\s\S]*?\])\s*```", re.MULTILINE)
    match = pattern.search(text)
    if match:
        json_text = match.group(1)
        return json_text
    else:
        start = text.find('[')
        end = text.rfind(']')
        if start != -1 and end != -1:
            return text[start:end+1]
        else:
            raise ValueError("JSON 데이터를 추출할 수 없습니다.")

def analyze_events_impact_batch(events_batch):
    """
    여러 이벤트(최대 10개씩)의 정보를 바탕으로 AI 분석을 한 번만 요청합니다.
    각 이벤트에 대해 예상 영향력(-100 ~ +100)(긍정적이고, 영향력이 클수록 +100)(부정적이고 영향력이 클수록 -100)과 한 줄 요약을 반환하는 JSON 배열을 받아옵니다.
    반환 예시: [{"expect": "70", "reason": "긍정적 영향"}, ...]
    만약 API 응답이 빈 문자열이거나 파싱에 실패하면, 해당 배치의 모든 이벤트에 대해 기본 결과를 반환합니다.
    """
    prompt = (
        "다음 이벤트들이 비트코인 가격에 미칠 영향을 예측해줘. "
        "각 이벤트에 대해 예상 영향력(-100 ~ +100)(긍정적이고, 영향력이 클수록 +100)(부정적이고 영향력이 클수록 -100)을 나타내고 "
        "한 줄로 요약해줘. 응답은 반드시 JSON 배열 형식으로 반환되어야 하며, "
        "각 결과는 {\"expect\": \"값\", \"reason\": \"요약\"} 형태여야 하고, 입력 순서와 동일해야 해.\n\n"
    )
    for i, event in enumerate(events_batch, start=1):
        title = event.get("Event", "정보 없음")
        currency = event.get("Currency", "정보 없음")
        actual = event.get("Actual", "")
        forecast = event.get("Forecast", "")
        previous = event.get("Previous", "")
        prompt += f"이벤트 {i}:\n"
        prompt += f"  이벤트: {title}\n"
        prompt += f"  통화: {currency}\n"
        prompt += f"  실제: {actual}\n"
        prompt += f"  예측: {forecast}\n"
        prompt += f"  이전: {previous}\n\n"
    
    try:
        response = geminaiclient.models.generate_content(
            model="gemini-2.0-flash", contents=[prompt]
        )
        text = response.text.strip()
        print("Gemini API 응답 디버그:", text)
        if not text:
            raise ValueError("응답이 비어 있음")
        # 추출: 응답이 코드 블록 형식이라면 JSON 부분만 추출
        try:
            json_text = extract_json(text)
        except Exception as e:
            print(f"JSON 추출 오류: {e} - 전체 텍스트: {text}")
            json_text = text  # 추출 실패 시 전체 텍스트로 처리
        analysis_list = json.loads(json_text)
        parsed_analysis_list = []
        for item in analysis_list:
            if isinstance(item, str):
                try:
                    parsed_item = json.loads(item.strip())
                    parsed_analysis_list.append(parsed_item)
                except Exception as e:
                    print(f"분석 응답 항목 파싱 오류: {e} - 원본 항목: {item}")
                    parsed_analysis_list.append({"expect": "N/A", "reason": f"❌ 파싱 오류: {e}"})
            else:
                parsed_analysis_list.append(item)
        if not isinstance(parsed_analysis_list, list) or len(parsed_analysis_list) != len(events_batch):
            raise ValueError("응답 형식이 올바르지 않습니다.")
        return parsed_analysis_list
    except Exception as e:
        print(f"AI 분석 오류: {e}")
        return [{"expect": "N/A", "reason": f"❌ API 오류: {e}"} for _ in events_batch]

def update_schedule_with_analysis():
    """
    저장된 일정 데이터의 모든 이벤트에 대해 AI 분석을 배치(10개씩)로 수행하여 'Prediction' 필드를 새로 갱신하고 파일을 업데이트합니다.
    (이미 분석 결과가 있더라도 새로 분석합니다.)
    """
    global schedule_data
    if schedule_data is None:
        print("일정 데이터가 없습니다.")
        return
    batch_size = 10
    events_to_analyze = schedule_data  # 모든 이벤트 대상으로 재분석
    for i in range(0, len(events_to_analyze), batch_size):
        batch = events_to_analyze[i:i+batch_size]
        analysis_results = analyze_events_impact_batch(batch)
        for event, analysis in zip(batch, analysis_results):
            event["Prediction"] = analysis
            print(f"이벤트 '{event.get('Event', '정보 없음')}' 분석 결과 갱신: {analysis}")
    save_schedule()

def get_prediction(e):
    """Prediction 필드가 문자열이면 추가로 JSON 파싱을 시도합니다."""
    pred = e.get("Prediction", {"expect": "N/A", "reason": "분석 결과 없음"})
    if isinstance(pred, str):
        try:
            pred = json.loads(pred.strip())
        except Exception as ex:
            print(f"Prediction 파싱 오류: {ex} - 원본: {pred}")
            pred = {"expect": pred.strip(), "reason": "파싱 오류"}
    return pred

@bot.command(name="upload")
async def upload_f(ctx):
    """
    파일 업로드 명령어.
    !upload 명령어와 함께 파일을 첨부하면 해당 파일을 SCHEDULE_FILE로 저장합니다.
    """
    if not ctx.message.attachments:
        await ctx.send("파일을 첨부해주세요!")
        return
    attachment = ctx.message.attachments[0]
    try:
        content = await attachment.read()
        with open(SCHEDULE_FILE, "wb") as f:
            f.write(content)
        load_schedule()
        await ctx.send("파일이 저장되었습니다!")
    except Exception as e:
        await ctx.send(f"파일 저장 오류: {e}")

@bot.command(name="analyze")
async def analyze_f(ctx):
    """
    저장된 일정 데이터에 대해 AI 분석을 배치(10개씩)로 수행하여 각 일정의 비트코인 가격 영향 예측 결과를 새로 갱신합니다.
    완료 후 업데이트된 파일을 저장합니다.
    """
    load_schedule()
    if schedule_data is None:
        await ctx.send("저장된 일정 파일이 없습니다. 먼저 !upload 명령어로 파일을 업로드하세요.")
        return
    await ctx.send("AI 분석을 시작합니다. 잠시만 기다려주세요...")
    update_schedule_with_analysis()
    await ctx.send("AI 분석이 완료되어 일정 데이터에 결과가 갱신되었습니다.")

@bot.command(name="schedule")
async def schedule_f(ctx, arg: str = None):
    """
    일정 조회 명령어.
    
    사용법:
    !schedule             → 사용법 안내 및 현재 저장된 일정의 날짜 범위를 보여줌.
    !schedule today       → 오늘 일정과 AI 분석 결과만 보여줌.
    !schedule all         → 전체 일정을 날짜별로 나누어 AI 분석 결과와 함께 보여줌.
    """
    load_schedule()
    if schedule_data is None:
        await ctx.send("저장된 일정 파일이 없습니다. 먼저 !upload 명령어로 파일을 업로드하세요.")
        return

    events = []
    for event in schedule_data:
        try:
            event_dt = datetime.fromisoformat(event["Datetime"])
            event["ParsedDatetime"] = event_dt
            events.append(event)
        except Exception as e:
            print(f"이벤트 파싱 오류: {e}")
            continue
    def get_emoji(prediction):
        """
        prediction 딕셔너리의 'expect' 값이 양수이면 초록, 음수이면 빨강, 0이면 중립 이모지를 반환합니다.
        예외 발생 시 빈 문자열을 반환합니다.
        """
        try:
            val_str = prediction.get('expect', '0')
            # 만약 값에 '%' 기호가 있다면 제거합니다.
            val_str_clean = val_str.replace('%', '').strip()
            # 부호(+, -)와 숫자, 소수점만 남깁니다.
            value = float(val_str_clean)
            if value > 0:
                return "🟢"
            elif value < 0:
                return "🔴"
            else:
                return "⚪"
        except Exception as e:
            return ""

    def format_event(e):
        """
        이벤트 정보를 포맷팅하여 반환합니다. AI 분석 결과에 따라 적절한 이모지를 추가합니다.
        """
        dt_str = e["ParsedDatetime"].strftime("%Y-%m-%d %H:%M")
        prediction = get_prediction(e)
        emoji = get_emoji(prediction)
        return (f"**{dt_str}** - {e['Currency']} - {e['Event']}\n"
                f"실제: {e['Actual']}, 예측: {e['Forecast']}, 이전: {e['Previous']}\n"
                f"**🤖AI 분석:** {emoji} 예상 영향: {prediction.get('expect')}%, 이유: {prediction.get('reason')}")

    if arg is None or arg.lower() not in ["today", "all"]:
        if events:
            dates = [e["ParsedDatetime"].date() for e in events]
            min_date = min(dates)
            max_date = max(dates)
            msg = (
                "사용법:\n"
                "`!schedule today` - 오늘 일정\n"
                "`!schedule all`   - 전체 일정 (하루 단위로 메시지 전송)\n\n"
                f"현재 저장된 일정은 {min_date}부터 {max_date}까지입니다."
            )
        else:
            msg = "일정 데이터가 없습니다."
        await ctx.send(msg)
    elif arg.lower() == "today":
        kst = pytz.timezone("Asia/Seoul")
        today = datetime.now(kst).date()
        today_events = [e for e in events if e["ParsedDatetime"].date() == today]
        if not today_events:
            await ctx.send("오늘 일정이 없습니다.")
            return
        today_events.sort(key=lambda x: x["ParsedDatetime"])
        msg_lines = ["##**오늘 일정:**"]
        for e in today_events:
            msg_lines.append(format_event(e))
        await ctx.send("\n\n".join(msg_lines))
    elif arg.lower() == "all":
        if not events:
            await ctx.send("저장된 일정이 없습니다.")
            return
        events_by_date = {}
        for e in events:
            date = e["ParsedDatetime"].date()
            events_by_date.setdefault(date, []).append(e)
        for date in sorted(events_by_date.keys()):
            day_events = events_by_date[date]
            day_events.sort(key=lambda x: x["ParsedDatetime"])
            msg_lines = [f"##**{date} 일정:**"]
            for e in day_events:
                msg_lines.append(format_event(e))
            await ctx.send("\n\n".join(msg_lines))
    else:
        await ctx.send("올바른 인수를 입력하세요: `today`, `all` 또는 인수 없이 사용하세요.")



@bot.command(name='market')
async def market(ctx):
    data = get_importance3_this_week_events()
    # 추출한 데이터를 텍스트 파일에 JSON 형식으로 저장
    with open("events.txt", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    message("이벤트 데이터가 events.txt 파일에 저장되었습니다.")

    

# 봇 명령어 정의
@bot.command(name='status')
async def get_status(ctx):
    global is_running, holding, count, order, leverage, n, current_side
    current_price_info = client.get_symbol_ticker(symbol=f"{symbol}")
    current_price = float(current_price_info['price'])
    position_info = get_futures_position_info(symbol)
    unrealizedProfit = float(position_info['unRealizedProfit'])
    positionAmt = float(position_info['positionAmt'])  # 포지션 수량
    entryprice = float(position_info['entryPrice'])  # 진입가격
    inv_amount = entryprice * positionAmt / leverage  # 투입금액
    if inv_amount != 0:
        pnl = unrealizedProfit / inv_amount * 100  # PNL
    else:
        pnl = 0
    liquidation_price = position_info['liquidationPrice']

    blnc = get_futures_asset_balance()

    embed = discord.Embed(title="Trading Bot Status", color=discord.Color.blue())
    embed.add_field(name="현재 상태", value='🟢매수중' if positionAmt != 0 else '🔴매수 대기중', inline=True)
    embed.add_field(name="현재 가격", value=f"{current_price}", inline=True)
    embed.add_field(name="현재 포지션", value=f"{current_side}", inline=True)
    embed.add_field(name="현재 PNL", value=f"{pnl}%", inline=True)
    embed.add_field(name="잔액", value=f"{blnc} USDT", inline=True)
    embed.add_field(name="매수 금액", value=f"{inv_amount}", inline=True)
    embed.add_field(name="현재 금액", value=f"{inv_amount + unrealizedProfit}", inline=True)
    embed.add_field(name="💸현재 수익", value=f"{unrealizedProfit}", inline=True)
    embed.add_field(name="추가 매수 횟수", value=f"{count}", inline=True)
    embed.add_field(name="청산 금액", value=f"{liquidation_price}", inline=True)    
    embed.add_field(name="주문 상태", value=f"{order}", inline=True)
    embed.add_field(name="레버리지", value=f"{leverage}", inline=True)
    embed.add_field(name="n값", value=f"{n}", inline=True)


    await ctx.send(embed=embed)


@bot.command(name='tendency')
async def tendency(ctx):
    candles = get_candles(symbol,interval='5m',candle_count=100)  # 필요한 경우 조정 가능
    file_path = create_tendency_chart(candles)
    
    # 이미지 파일을 디스코드에 전송
    await ctx.send(file=discord.File(file_path))
    
    # 사용 후 이미지 파일 삭제
    os.remove(file_path)

@bot.command(name='start')
async def start(ctx):
    global is_running
    if not is_running:
        is_running = True
        await ctx.send("자동매매를 시작합니다")
        bot.loop.create_task(start_trading_strategy())
    else:
        await ctx.send("자동매매가 이미 실행 중입니다")

@bot.command(name='stop')
async def stop(ctx):
    global is_running
    if is_running:
        is_running = False
        await ctx.send("자동매매가 중단되었습니다")
    else:
        await ctx.send("자동매매가 실행 중이 아닙니다")

@bot.command(name='close')
async def close_positions(ctx):
    await ctx.send("정말 하시겠습니까? [Y/n]")

    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel and m.content.lower() in ['y', 'n']

    try:
        msg = await bot.wait_for('message', check=check, timeout=30.0)
        if msg.content.lower() == 'y':
            global is_running
            is_running = False
            close(symbol)
            await ctx.send(f"{symbol} 포지션이 모두 청산되었습니다.")
        else:
            await ctx.send("포지션 청산이 취소되었습니다.")
    except asyncio.TimeoutError:
        await ctx.send("시간 초과로 포지션 청산이 취소되었습니다.")


@bot.command(name='set_n')
async def set_n(ctx, value: int):
    global n
    n = value
    await ctx.send(f"n 변수가 {n}로 설정되었습니다.")

@bot.command(name='set_count')
async def set_count(ctx, value: int):
    global count
    count = value
    await ctx.send(f"count 변수가 {value}로 설정되었습니다.")

@bot.command(name='target_pnl')
async def target_pnl_f(ctx, value: int):
    global target_pnl
    target_pnl = value
    await ctx.send(f"target_pnl 변수가 {target_pnl}로 설정되었습니다.")

@bot.command(name='safe_pnl')
async def safe_pnl_f(ctx, value: int):
    global safe_pnl
    safe_pnl = value
    await ctx.send(f"safe_pnl 변수가 {safe_pnl}로 설정되었습니다.")


@bot.command(name='set_leverage')
async def set_lev(ctx, value: int):
    global leverage, symbol
    leverage = value
    set_leverage(symbol,leverage)
    await ctx.send(f"레버리지가 {value}로 설정되었습니다.")



@bot.command(name='waiting')
async def wait_(ctx):
    global waiting
    if waiting == False:
        waiting = True
    else:
        waiting = False
    await ctx.send(f"waiting가 {waiting}로 설정되었습니다")

@bot.command(name='setting')
async def setting(ctx):
    global target_pnl, safe_pnl, count, n, leverage, stoploss_pnl
    global waiting

    embed = discord.Embed(title="Trading Bot Status", color=discord.Color.blue())
    embed.add_field(name="target_pnl", value=f"{target_pnl}%", inline=True)
    embed.add_field(name="safe_pnl", value=f"{safe_pnl}%", inline=True)
    embed.add_field(name="count", value=f"{count}", inline=True)
    embed.add_field(name="초기 투자비용 비율", value=f"{n}", inline=True)
    embed.add_field(name="stoploss_pnl", value=f"{stoploss_pnl}", inline=True)
    embed.add_field(name="레버리지", value=f"{leverage}", inline=True)
    embed.add_field(name="waiting", value=f"{waiting}", inline=True)

    await ctx.send(embed=embed)

@bot.command(name='buy') # 현재가격으로 구매 : !buy 구매수량(달러)
async def buycommand(ctx,value: float):
    global is_running, sell_price, sell_date, holding, count, order, leverage, max_pnl, n
    
    current_price_info = client.get_symbol_ticker(symbol=f"{symbol}")
    current_price = float(current_price_info['price'])
    inv_amount = value  # 투입할 금액

    order_price = round(current_price*1.001, 1)
    inv_size = round(inv_amount / current_price * leverage, 3)
    order = place_limit_order(symbol, order_price,quantity=inv_size, leverage=leverage,side='BUY')
    message(f"[명령어]매수주문완료\n현재가격 : {current_price}\n추가매수횟수 : {count}\n매수금액 : {inv_amount}\n레버리지 : {leverage}")
    await ctx.send(f"주문완료")



@bot.command(name='check_order')
async def check_order(ctx):
    global order
    await ctx.send(f"order : {order}")




@bot.command(name="database")
async def database(ctx, action: str, *args):
    if action == "show":
        try:
            limit = int(args[0]) if args else None
            data = fetch_from_db(limit)
            if data:
                response = "\n".join([f"DATE : {row[0]} | SIDE : {row[1]} | RESULT : {row[2]} | LEVERAGE : {row[3]} | REALIZED PROFIT : {row[4]} | PNL: {row[5]:.2f}% | INVEST AMOUNT : {row[6]:.2f} | COUNT : {row[7]} | MAX PNL : {row[8]:.2f} | MIN PNL : {row[9]:.2f} | HOLDING TIME : {row[10]}" for row in data])
            else:
                response = "데이터가 없습니다."
        except ValueError:
            response = "숫자를 입력해주세요."
        await ctx.send(response)

    elif action == "all":
        data = fetch_from_db()
        if data:
            response = "\n".join([f"DATE : {row[0]} | SIDE : {row[1]} | RESULT : {row[2]} | LEVERAGE : {row[3]} | REALIZED PROFIT : {row[4]} | PNL: {row[5]:.2f}% | INVEST AMOUNT : {row[6]:.2f} | COUNT : {row[7]} | MAX PNL : {row[8]:.2f} | MIN PNL : {row[9]:.2f} | HOLDING TIME : {row[10]}" for row in data])
        else:
            response = "데이터가 없습니다."
        await ctx.send(response)

    elif action == "clear":
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DROP TABLE IF EXISTS data")
        conn.commit()
        conn.close()
        init_db()
        await ctx.send("데이터베이스가 초기화되었습니다.")

    else:
        await ctx.send("알 수 없는 명령어입니다. 사용 가능한 명령어: show, all, clear")

@bot.command(name="save")
async def save(ctx, date: str, side: str, result: str, leverage: float, realized_profit: float, roi: float, inv_amount: float, count_value:float, max_pnl:float, min_pnl:float, time:str):
    try:
        save_to_db(date, side, result, leverage, realized_profit, roi, inv_amount, count_value, max_pnl, min_pnl, time)
        await ctx.send(f"데이터가 저장되었습니다.")
    except Exception as e:
        await ctx.send(f"오류가 발생했습니다: {e}")

@bot.command(name='helpme')
async def helpme(ctx):

    await ctx.send('''
                   
!set_n : 투자비용 비율 조정 (전체시드/2^n)
!set_count : 추가매수 횟수 변수 조정
!target_pnl : target_pnl 변수 조정
!safe_pnl : safe_pnl 변수 조정
!set_leverage : 레버리지 세팅
!close : 포지션 청산
!stop : 자동매매 중단
!start : 자동매매 시작
!tendency : 최근 차트 전송
!status : 현재 상태
!setting : 설정값 목록
!database show <number> : 거래내역 보기
!database all : 모든 거래내역 보기
!database clear : 거래내역 초기화
!save : 거래내역 추가
!schedule : 일정 보기
!schedule today : 오늘 일정 보기
!schedule all : 저장된 전체 일정 보기
!upload : 일정 데이터 업로드
!analyze : 일정 데이터 AI분석
!market : 일정 데이터 가져오기기
!buy <USDT> : 현재 가격으로 구매하기(롱)
!aianalogy : ai분석 실시
!credit : 크레딧
!helpme : 지금 보는 내용
!update : 패치노트 보기
!check_order : order 상태 보기
!waiting : waiting 변수 토글글
''')
    
@bot.command(name='aianalogy')
async def aianalogy(ctx):
    global Aicommand
    Aicommand = True
    await ctx.send(f"Ai분석 실시.")

@bot.command(name='credit')
async def credit(ctx):
    await ctx.send('''

    윈터띠 단타봇
    ver 1.1
    last update 2025-03
    made by 윈터띠

''')

@bot.command(name='update')
async def update(ctx):
    with open("PATCHNOTE.txt", "r",encoding="utf-8") as file:
        text = file.read()
        await ctx.send(f"```{text}```")

@bot.event
async def on_ready():
    # 로딩 애니메이션: "로딩중..." 메시지와 회전하는 화살표
    os.system("cls" if os.name == "nt" else "clear")
    spinner = ['|', '/', '-', '\\']
    print(f"{Fore.LIGHTBLACK_EX}Loading ...", end=" ", flush=True)
    for i in range(20):  # 반복 횟수를 조절하여 애니메이션 지속 시간 결정 (약 2초)
        sys.stdout.write(f"{Fore.LIGHTBLACK_EX}{spinner[i % len(spinner)]}{Style.RESET_ALL}")
        sys.stdout.flush()
        time.sleep(0.1)
        sys.stdout.write('\b')

    os.system("cls" if os.name == "nt" else "clear")

    art = f'''{Fore.LIGHTGREEN_EX}
===================================
_._     _,-'""`-._     TRADING BOT
(,-.`._,'(       |\`-/| 2025
    `-.-' \ )-`( , o o)
        `-    \`_`"'-
===================================
'''
    print(art)
    time.sleep(0.5)
    print(f"{Fore.GREEN}We have logged in as {bot.user}{Style.RESET_ALL}")
    
    

## 기본 전략
async def start_trading_strategy():
    global is_running, sell_price, sell_date, holding, count, order, leverage, max_pnl, waiting, Aicommand
    global loss_amount, stoploss_pnl, safe_pnl, target_pnl, current_side

    sell_date = datetime.today()
    sell_price = 0
    ready_date = datetime.today()
    last_buy_date = datetime.today()
    
    sta = None
    current_price = None
    blnc = 0
    inv_amount = 0
    unrealizedProfit = 0
    pnl = 0

    loss_amount = 0


    holding = False  # 매수상태일때 True
    count = 0
    order = None
    max_pnl = 0  # 최고 수익률 초기화
    min_pnl = 0

    file_path = 0
    ready_side = None
    savemode = False

    long_ready_price = None
    short_ready_price = None

    position_list = []
    buytime_list = []


    print("Trading strategy started")
    message("자동매매를 시작합니다")
    set_leverage(symbol,initial_leverage)

    while is_running:
        try:

            # 매수상태 체킹 코드
            position_info = get_futures_position_info(symbol)
            
            if position_info != 0 and float(position_info['positionAmt']) != 0:
                holding = True
                order = get_latest_order(symbol)
                order_id = order['orderId']
                order = check_order_status(symbol, order_id)
                if order is not None:
                    if order and order['status'] == 'FILLED':
                        message(f"{order_id}\n주문이 체결되었습니다.")
                        order = None
                        waiting = False
                        if addb_status is True:
                            addb_status = False
                    else:
                        waiting = True
                else:
                    waiting = False


            else:
                holding = False

            cancel_old_orders(client, symbol)


            now = datetime.now()
            current_price_info = client.get_symbol_ticker(symbol=f"{symbol}")
            current_price = float(current_price_info['price'])
            position_info = get_futures_position_info(symbol)
            unrealizedProfit = float(position_info['unRealizedProfit'])
            positionAmt = float(position_info['positionAmt'])  # 포지션 수량

            if positionAmt > 0:
                current_side = 'long'
            elif positionAmt < 0:
                current_side = 'short'
            else:
                current_side = None

            entryprice = float(position_info['entryPrice'])  # 진입가격
            # inv_amount = entryprice * positionAmt / leverage  # 투입금액
            inv_amount = abs(positionAmt) * entryprice / leverage

            if inv_amount != 0:
                pnl = unrealizedProfit / inv_amount * 100  # PNL
            else:
                pnl = 0
            liquidation_price = position_info['liquidationPrice']

            if holding is False:
                sta = 'pending purchase'
            else:
                sta = 'Currently holding'
            blnc = get_futures_asset_balance()

            msg_current_status = f'''
### Current Status:
Status : {sta}
Balance : {blnc}
Leverage : {leverage}
Current Side : {current_side}
Purchase Amount : {inv_amount}
Valuation Amount : {inv_amount + unrealizedProfit}
Current Rate of Return : {pnl}%
'''

     

            ########## 초기매수 
            if order is None:
                if Aicommand is True or ((now.minute)%20) == 0:
                    long_response, short_response = check_spike(symbol,msg_current_status)

                    long_decision = long_response.get('decision') if long_response else None
                    long_price = long_response.get('price') if long_response else None
                    long_reason = long_response.get('reason') if long_response else None
                    short_decision = short_response.get('decision') if short_response else None
                    short_price = short_response.get('price') if short_response else None
                    short_reason = short_response.get('reason') if short_response else None


                    msg_ai = f'''
# 🤖 AI ANALYSIS 
현재 상태 : {sta}
현재 시간 : {now} 
현재 가격 : {current_price}
## 🟩 LONG
```
DECISION : {long_decision}
PRICE : {long_price}
REASON : {long_reason}
``` 
## 🟥 SHORT
```
DECISION : {short_decision}
PRICE : {short_price}
REASON : {short_reason}
``` 
'''                 
                    message(msg_ai)
                    if  holding is False:
                        if long_decision == 'good' and short_decision == 'bad':
                            long_ready_price = float(long_price) if long_price != 'null' else None
                            ready_status = True
                            ready_date = now
                            ready_side = 'long'
                        elif long_decision == 'bad' and short_decision == 'good':
                            short_ready_price = float(short_price) if short_price != 'null' else None
                            ready_status = True
                            ready_date = now
                            ready_side = 'short'
                        elif long_decision == 'good' and short_decision == 'good':
                            longdiff = abs(current_price-long_price)
                            shortdiff = abs(current_price-short_price)
                            if longdiff > shortdiff:
                                short_ready_price = float(short_price) if short_price != 'null' else None
                                ready_status = True
                                ready_date = now
                                ready_side = 'short'
                            elif longdiff <= shortdiff:
                                long_ready_price = float(long_price) if long_price != 'null' else None
                                ready_status = True
                                ready_date = now
                                ready_side = 'long'
                    else:
                        if long_decision == 'bad' and short_decision == 'bad':
                            addb_status = False
                        else:
                            addb_status = True
                        

                    diff = now - ready_date
                    if diff.total_seconds() >= 60*60*3:
                        ready_status = False

                    
                    Aicommand = False
                    await asyncio.sleep(60)

                
                if long_ready_price and ready_side == 'long' and ready_status is True and current_price <= long_ready_price and ((now.minute)%5) == 4:
                    if is_good_to_buy(symbol,'long') is True:
                        percentage = 100 / (2 ** n)
                        order = execute_limit_order(symbol,current_price,percentage,leverage,'BUY')
                        iquantity = calculate_order_quantity(percentage)
                        msg_long = f'''
## 🚀 매수주문완료
```
포지션 : 🟩LONG
현재가격 : {current_price}
레버리지 : {leverage}
매수금액 : {iquantity}
```
'''
                        message(msg_long)
                        ready_status = False
                        long_ready_price = 0
                        short_ready_price = 0
                        ready_side = None
                        buytime_list.append(now)
                
                if short_ready_price and ready_side == 'short' and ready_status is True and current_price >= short_ready_price and ((now.minute)%5) == 4:
                    if is_good_to_buy(symbol,'short') is True:
                        percentage = 100 / (2 ** n)
                        order = execute_limit_order(symbol,current_price,percentage,leverage,'SELL')
                        iquantity = calculate_order_quantity(percentage)
                        msg_short = f'''
## 🚀 매수주문완료
```
포지션 : 🟥SHORT
현재가격 : {current_price}
레버리지 : {leverage}
매수금액 : {iquantity}
```
'''
                        message(msg_short)
                        ready_status = False
                        long_ready_price = 0
                        short_ready_price = 0
                        ready_side = None
                        buytime_list.append(now)
            
            # min, max pnl 갱신
            if holding is True:
                if pnl < min_pnl:
                    min_pnl = pnl

                if pnl > max_pnl:
                    max_pnl = pnl

                time_diff = now - buytime_list[0]

            ########## 매도
            if order is None and holding is True:
                if max_pnl < 10 and pnl > safe_pnl and (time_diff.total_seconds()/60) > 60*3:
                    order = close(symbol)
                    savemode = True
                if pnl >= target_pnl: # 익절
                    order = close(symbol)
                    savemode = True
                elif current_side == 'short' and pnl >= target_pnl-5:
                    order = close(symbol)
                    savemode = True

                if current_side == 'long' and count == 1 and pnl < -stoploss_pnl: # 손절(추매1번 롱)
                    if pnl > -(stoploss_pnl+5) and long_ready_price != 'null' and abs(current_price - long_ready_price)/long_ready_price <= 0.005:
                        continue
                    else:
                        order = close(symbol)
                        savemode = True
                elif count == 0 and pnl < -(stoploss_pnl+3): # 손절(추매0번 롱숏)
                    if current_side == 'long':
                        if pnl > -(stoploss_pnl+8) and long_ready_price and abs(current_price - long_ready_price)/long_ready_price <= 0.005:
                            continue
                        else:
                            order = close(symbol)
                            savemode = True
                    elif current_side == 'short':
                        if pnl > -(stoploss_pnl+8) and short_ready_price and abs(current_price - short_ready_price)/long_ready_price <= 0.005:
                            continue
                        else:
                            order = close(symbol)
                            savemode = True
                

                ## 추매

                if pnl < -add_pnl and addb_status is True:
                    if current_side == 'long' and current_price <= long_ready_price and ((now.minute)%5) == 4:
                        if is_good_to_buy(symbol,'long') is True:
                            order_price = round(current_price,1)
                            inv_size = round(inv_amount / current_price * leverage, 3)
                            order = place_limit_order(symbol, order_price, inv_size, leverage,'BUY')
                            iquantity = calculate_order_quantity(percentage)
                            msg_long = f'''
## 🚀 추가매수주문완료
```
포지션 : 🟩LONG
현재가격 : {current_price}
레버리지 : {leverage}
매수금액 : {iquantity}
```
'''
                            message(msg_long)
                            ready_status = False
                            long_ready_price = 0
                            short_ready_price = 0
                            buytime_list.append(now)
                            count += 1
                            waiting = True

                    elif current_side == 'short' and current_price >= short_ready_price and ((now.minute)%5) == 4:
                        if is_good_to_buy(symbol,'short') is True:
                            order_price = round(current_price,1)
                            inv_size = round(inv_amount / current_price * leverage, 3)
                            order = place_limit_order(symbol, order_price, inv_size, leverage,'SELL')
                            iquantity = calculate_order_quantity(percentage)
                            msg_short = f'''
## 🚀 추가매수주문완료
```
포지션 : 🟥SHORT
현재가격 : {current_price}
레버리지 : {leverage}
매수금액 : {iquantity}
```
'''
                            message(msg_short)
                            ready_status = False
                            long_ready_price = 0
                            short_ready_price = 0
                            buytime_list.append(now)
                            count += 1
                            waiting = True




            ########## 결과 저장하기 & 디코메세지 보내기
            if savemode is True:
                result = 'profit' if pnl >= 0 else 'loss'
                time_diff = str(buytime_list[0] - now)
                save_to_db(now, current_side, result, leverage, unrealizedProfit, pnl, inv_amount, count, max_pnl, min_pnl, time_diff)

                candle_count = required_candle_count(position_list,'5m')
                if candle_count >= 600:
                    candle_count /= 12
                    candle_count = int(candle_count)
                    interval = '1h'
                elif candle_count >= 300:
                    candle_count /= 3
                    candle_count = int(candle_count)
                    interval = '15m'
                else:
                    interval = '5m'

                candles = get_candles(symbol,interval,candle_count)

                position_list = [current_side,buytime_list,now]

                file_path = create_tendency_chart(candles,position_list,interval)
                result_ = '🟢profit' if pnl > 0 else '🔴loss'
                side_ = '🟩LONG' if current_side == 'long' else '🟥SHORT'
                msg = f'''
                # 📊 POSITION RESULT
                ```
                DATE                 :  {now}
                SIDE                 :  {side_}
                Result               :  {result_}
                Leverage             :  {leverage}
                REALIZED PROFIT      :  {unrealizedProfit}
                ROI                  :  {pnl}%
                Invest Amount        :  {inv_amount}
                Additional Purchaces :  {count}
                Max Pnl              :  {max_pnl}%
                Min Pnl              :  {min_pnl}%
                Holding time         :  {time_diff}
                ```
                '''

                message_data(msg,file_path)

                # 초기화
                leverage = initial_leverage
                count = 0
                max_pnl = 0
                min_pnl = 0
                buytime_list = []
                savemode = False


                        

            now = datetime.now()
            if now.minute == 0:  # 정시(00분)인지 확인
                if holding is False:
                    status = '🔴매수 대기중'
                else:
                    status = '🟢매수중'
                blnc = get_futures_asset_balance()

                if current_side == 'long':
                    current_side_msg = '🟩LONG' 
                elif current_side == 'short':
                    current_side_msg = '🟥SHORT'
                else:
                    current_side_msg = '⬜WAITING'


                msg = f'''
# 🪙 STATUS
```
현재 상태 : {status}
현재 가격 : {current_price}
현재 포지션 : {current_side_msg}
현재 pnl : {pnl}
잔액 : {blnc}
매수금액 : {inv_amount}
현재금액 : {inv_amount + unrealizedProfit}
현재 수익 : {unrealizedProfit}
추가매수횟수 : {count}
주문 상태 : {order}
레버리지 : {leverage}
```
                '''
                message(msg)
                await asyncio.sleep(60)

            await asyncio.sleep(10)
        except Exception as e:
            error_log = f"""
            오류 발생: {e}
            위치: {traceback.format_exc()}
            현재 상태:
            holding: {holding}
            current_price: {current_price}
            sell_price: {sell_price}
            """
            message(error_log)
