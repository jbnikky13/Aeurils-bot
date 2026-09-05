import os

REQUIRED = ('TELEGRAM_BOT_TOKEN','STOCK_API_KEY','WHALE_API_KEY')

def main():
    missing = [name for name in REQUIRED if not os.getenv(name)]
    if missing:
        raise SystemExit('Missing required secrets: ' + ', '.join(missing))
    print('Aeurils provider configuration: OK')

if __name__ == '__main__':
    main()
