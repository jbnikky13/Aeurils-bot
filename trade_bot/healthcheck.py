import os

REQUIRED=('TELEGRAM_BOT_TOKEN','GEMINI_API_KEY','STOCK_API_KEY','WHALE_API_KEY')
OPTIONAL=('TELEGRAM_CHAT_ID','COINGECKO_API_KEY')

def main():
    missing=[name for name in REQUIRED if not os.getenv(name)]
    if missing: raise SystemExit('Missing required secrets: '+', '.join(missing))
    if not os.getenv('TELEGRAM_CHAT_ID'): print('WARNING: TELEGRAM_CHAT_ID is not set; scheduled delivery is disabled.')
    if not os.getenv('COINGECKO_API_KEY'): print('INFO: COINGECKO_API_KEY absent; CoinGecko remains optional.')
    print('Aeurils provider configuration: OK')

if __name__=='__main__': main()
