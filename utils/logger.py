import logging
import os
from logging.handlers import RotatingFileHandler

def setup_logger(name, log_file, level=logging.DEBUG):
    """Function to setup as many loggers as you want"""
    
    # Ensure logs directory exists
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')

    # File Handler
    handler = RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5)
    handler.setFormatter(formatter)

    # Console Handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO) # Console shows INFO and above

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.addHandler(handler)
    logger.addHandler(console_handler)

    return logger

# Create the main app logger
logger = setup_logger('TradingBot', 'logs/trade_detailed.log')

def log_thinking(message):
    """Special function to log the bot's thinking process"""
    logger.debug(f"[THOUGHT] {message}")
