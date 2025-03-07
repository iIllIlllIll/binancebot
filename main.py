import discord
from discord.ext import commands
import requests
from bs4 import BeautifulSoup
import time
from datetime import datetime, timedelta, timezone
from binance.client import Client
from binance.enums import *
import asyncio
import matplotlib
matplotlib.use('Agg')  # 서버 환경에서 GUI 없이 사용
import sqlite3
import mplfinance as mpf
import pandas as pd
import tempfile
import os
import traceback
import base64
import json
from openai import OpenAI

from functions import *
from discord_functions import *



# setup(bot)

init_db()
bot.run(TOKEN)