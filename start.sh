#!/bin/bash

# Create virtual environment and install packages
python3 -m venv env
source env/bin/activate 
pip3 install -r requirements.txt

# Run the bot
python3 bot.py
