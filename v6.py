
global CPU_THRESHOLD
global RAM_THRESHOLD
global PREFIX
global VPS_USER_ROLE_ID
global BOT_NAME
global DEFAULT_STORAGE_POOL
global BOT_VERSION
global BOT_DEVELOPER
global resource_monitor_active
global MAIN_ADMIN_ID
global YOUR_SERVER_IP
import discord
from discord.ext import commands
import asyncio
import subprocess
import json
from datetime import datetime, timedelta, timezone
import shlex
import logging
import shutil
import os
from typing import Optional, List, Dict, Any
import threading
import time
import sqlite3
import random
import requests
from dotenv import load_dotenv
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
if not DISCORD_TOKEN:
    raise ValueError('DISCORD_TOKEN environment variable is required! Set it in .env file or environment.')
else:
    BOT_NAME = os.getenv('BOT_NAME', 'Svm6-Bot')
    PREFIX = os.getenv('PREFIX', '!')
    YOUR_SERVER_IP = os.getenv('YOUR_SERVER_IP', '127.0.0.1')
    MAIN_ADMIN_ID = int(os.getenv('MAIN_ADMIN_ID', '0'))
    VPS_USER_ROLE_ID = int(os.getenv('VPS_USER_ROLE_ID', '0'))
    DEFAULT_STORAGE_POOL = os.getenv('DEFAULT_STORAGE_POOL', 'default')
    BOT_VERSION = os.getenv('BOT_VERSION', '8.0-PRO')
    BOT_DEVELOPER = os.getenv('BOT_DEVELOPER', 'AnkitDev')
    OS_OPTIONS = [{'label': 'Ubuntu 20.04 LTS', 'value': 'ubuntu:20.04'}, {'label': 'Ubuntu 22.04 LTS', 'value': 'ubuntu:22.04'}, {'label': 'Ubuntu 24.04 LTS', 'value': 'ubuntu:24.04'}, {'label': 'Debian 10 (Buster)', 'value': 'images:debian/10'}, {'label': 'Debian 11 (Bullseye)', 'value': 'images:debian/11'}, {'label': 'Debian 12 (Bookworm)', 'value': 'images:debian/12'}, {'label': 'Debian 13 (Trixie)', 'value': 'images:debian/13'}]
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', handlers=[logging.FileHandler('bot.log'), logging.StreamHandler()])
    logger = logging.getLogger(f'{BOT_NAME.lower()}_vps_bot')
    def get_db():
        """Get database connection with proper timeout and WAL mode"""
        conn = sqlite3.connect('vps.db', timeout=60.0, check_same_thread=False, isolation_level=None)
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA busy_timeout=60000')
        conn.execute('PRAGMA synchronous=NORMAL')
        conn.row_factory = sqlite3.Row
        return conn
    async def run_in_executor(func, *args):
        """Run blocking database operations in thread executor"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, func, *args)
    def init_db():
        conn = get_db()
        cur = conn.cursor()
        cur.execute('CREATE TABLE IF NOT EXISTS admins (\n        user_id TEXT PRIMARY KEY\n    )')
        cur.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (str(MAIN_ADMIN_ID),))
        cur.execute('CREATE TABLE IF NOT EXISTS nodes (\n        id INTEGER PRIMARY KEY AUTOINCREMENT,\n        name TEXT UNIQUE NOT NULL,\n        location TEXT,\n        total_vps INTEGER,\n        tags TEXT DEFAULT \'[]\',\n        api_key TEXT,\n        url TEXT,\n        is_local INTEGER DEFAULT 0\n    )')
        cur.execute('SELECT COUNT(*) FROM nodes WHERE is_local = 1')
        if cur.fetchone()[0] == 0:
            cur.execute('INSERT INTO nodes (name, location, total_vps, tags, api_key, url, is_local) VALUES (?, ?, ?, ?, ?, ?, ?)', ('Local Node', 'Local', 100, '[]', None, None, 1))
        cur.execute('CREATE TABLE IF NOT EXISTS vps (\n        id INTEGER PRIMARY KEY AUTOINCREMENT,\n        user_id TEXT NOT NULL,\n        node_id INTEGER NOT NULL DEFAULT 1,\n        container_name TEXT UNIQUE NOT NULL,\n        ram TEXT NOT NULL,\n        cpu TEXT NOT NULL,\n        storage TEXT NOT NULL,\n        config TEXT NOT NULL,\n        os_version TEXT DEFAULT \'ubuntu:22.04\',\n        status TEXT DEFAULT \'stopped\',\n        suspended INTEGER DEFAULT 0,\n        whitelisted INTEGER DEFAULT 0,\n        created_at TEXT NOT NULL,\n        shared_with TEXT DEFAULT \'[]\',\n        suspension_history TEXT DEFAULT \'[]\'\n    )')
        cur.execute('PRAGMA table_info(vps)')
        info = cur.fetchall()
        columns = [col[1] for col in info]
        if 'os_version' not in columns:
            cur.execute('ALTER TABLE vps ADD COLUMN os_version TEXT DEFAULT \'ubuntu:22.04\'')
        if 'node_id' not in columns:
            cur.execute('ALTER TABLE vps ADD COLUMN node_id INTEGER DEFAULT 1')
        cur.execute('CREATE TABLE IF NOT EXISTS settings (\n        key TEXT PRIMARY KEY,\n        value TEXT NOT NULL\n    )')
        settings_init = [('cpu_threshold', '90'), ('ram_threshold', '90')]
        for key, value in settings_init:
            cur.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', (key, value))
        cur.execute('CREATE TABLE IF NOT EXISTS port_allocations (\n        user_id TEXT PRIMARY KEY,\n        allocated_ports INTEGER DEFAULT 0\n    )')
        cur.execute('CREATE TABLE IF NOT EXISTS port_forwards (\n        id INTEGER PRIMARY KEY AUTOINCREMENT,\n        user_id TEXT NOT NULL,\n        vps_container TEXT NOT NULL,\n        vps_port INTEGER NOT NULL,\n        host_port INTEGER NOT NULL,\n        created_at TEXT NOT NULL\n    )')
        cur.execute('CREATE TABLE IF NOT EXISTS user_coins (\n        user_id TEXT PRIMARY KEY,\n        balance INTEGER DEFAULT 0,\n        total_earned INTEGER DEFAULT 0,\n        total_spent INTEGER DEFAULT 0,\n        last_daily TEXT,\n        invite_count INTEGER DEFAULT 0,\n        message_count INTEGER DEFAULT 0,\n        voice_minutes INTEGER DEFAULT 0,\n        created_at TEXT NOT NULL\n    )')
        cur.execute('CREATE TABLE IF NOT EXISTS coin_transactions (\n        id INTEGER PRIMARY KEY AUTOINCREMENT,\n        user_id TEXT NOT NULL,\n        amount INTEGER NOT NULL,\n        type TEXT NOT NULL,\n        description TEXT,\n        created_at TEXT NOT NULL\n    )')
        cur.execute('CREATE TABLE IF NOT EXISTS vps_expiration (\n        vps_id INTEGER PRIMARY KEY,\n        expires_at TEXT NOT NULL,\n        duration_days INTEGER NOT NULL,\n        auto_renew INTEGER DEFAULT 0,\n        renewal_notified INTEGER DEFAULT 0,\n        FOREIGN KEY (vps_id) REFERENCES vps(id)\n    )')
        cur.execute('CREATE TABLE IF NOT EXISTS deploy_plans (\n        id INTEGER PRIMARY KEY AUTOINCREMENT,\n        name TEXT UNIQUE NOT NULL,\n        description TEXT,\n        ram_gb INTEGER NOT NULL,\n        cpu_cores INTEGER NOT NULL,\n        disk_gb INTEGER NOT NULL,\n        duration_days INTEGER NOT NULL,\n        cost_coins INTEGER NOT NULL,\n        active INTEGER DEFAULT 1,\n        icon TEXT DEFAULT \'📦\',\n        created_at TEXT NOT NULL\n    )')
        cur.execute('CREATE TABLE IF NOT EXISTS resource_plans (\n        id INTEGER PRIMARY KEY AUTOINCREMENT,\n        name TEXT UNIQUE NOT NULL,\n        description TEXT,\n        ram_gb INTEGER NOT NULL,\n        cpu_cores INTEGER NOT NULL,\n        disk_gb INTEGER NOT NULL,\n        upgrade_cost INTEGER NOT NULL,\n        active INTEGER DEFAULT 1,\n        icon TEXT DEFAULT \'⚡\',\n        created_at TEXT NOT NULL\n    )')
        cur.execute('CREATE TABLE IF NOT EXISTS vps_upgrades (\n        id INTEGER PRIMARY KEY AUTOINCREMENT,\n        vps_id INTEGER NOT NULL,\n        user_id TEXT NOT NULL,\n        old_ram INTEGER,\n        old_cpu INTEGER,\n        old_disk INTEGER,\n        new_ram INTEGER,\n        new_cpu INTEGER,\n        new_disk INTEGER,\n        cost_coins INTEGER,\n        upgraded_at TEXT NOT NULL,\n        upgraded_by TEXT,\n        FOREIGN KEY (vps_id) REFERENCES vps(id)\n    )')
        cur.execute('CREATE TABLE IF NOT EXISTS invites (\n        id INTEGER PRIMARY KEY AUTOINCREMENT,\n        inviter_id TEXT NOT NULL,\n        invited_id TEXT NOT NULL,\n        joined_at TEXT NOT NULL,\n        coins_earned INTEGER DEFAULT 0\n    )')
        cur.execute('CREATE TABLE IF NOT EXISTS voice_sessions (\n        id INTEGER PRIMARY KEY AUTOINCREMENT,\n        user_id TEXT NOT NULL,\n        started_at TEXT NOT NULL,\n        ended_at TEXT,\n        duration_minutes INTEGER DEFAULT 0,\n        coins_earned INTEGER DEFAULT 0\n    )')
        cur.execute('CREATE TABLE IF NOT EXISTS coupon_codes (\n        id INTEGER PRIMARY KEY AUTOINCREMENT,\n        code TEXT UNIQUE NOT NULL,\n        coins INTEGER NOT NULL,\n        max_uses INTEGER DEFAULT NULL,\n        current_uses INTEGER DEFAULT 0,\n        expires_at TEXT DEFAULT NULL,\n        created_by TEXT NOT NULL,\n        created_at TEXT NOT NULL,\n        active INTEGER DEFAULT 1,\n        description TEXT\n    )')
        cur.execute('CREATE TABLE IF NOT EXISTS coupon_redemptions (\n        id INTEGER PRIMARY KEY AUTOINCREMENT,\n        coupon_id INTEGER NOT NULL,\n        user_id TEXT NOT NULL,\n        coins_received INTEGER NOT NULL,\n        redeemed_at TEXT NOT NULL,\n        FOREIGN KEY (coupon_id) REFERENCES coupon_codes(id)\n    )')
        cur.execute('CREATE TABLE IF NOT EXISTS rate_limits (\n        id INTEGER PRIMARY KEY AUTOINCREMENT,\n        user_id TEXT NOT NULL,\n        action_type TEXT NOT NULL,\n        action_count INTEGER DEFAULT 1,\n        window_start TEXT NOT NULL,\n        last_action TEXT NOT NULL,\n        UNIQUE(user_id, action_type)\n    )')
        cur.execute('CREATE TABLE IF NOT EXISTS security_logs (\n        id INTEGER PRIMARY KEY AUTOINCREMENT,\n        user_id TEXT NOT NULL,\n        activity_type TEXT NOT NULL,\n        description TEXT,\n        severity TEXT DEFAULT \'low\',\n        flagged INTEGER DEFAULT 0,\n        created_at TEXT NOT NULL,\n        additional_data TEXT\n    )')
        cur.execute('CREATE TABLE IF NOT EXISTS user_trust (\n        user_id TEXT PRIMARY KEY,\n        trust_score INTEGER DEFAULT 100,\n        warnings INTEGER DEFAULT 0,\n        violations INTEGER DEFAULT 0,\n        last_violation TEXT,\n        restricted INTEGER DEFAULT 0,\n        notes TEXT\n    )')
        cur.execute('SELECT COUNT(*) as count FROM deploy_plans')
        if cur.fetchone()['count'] == 0:
            default_deploy_plans = [('Starter', 'Perfect for testing and learning', 1, 1, 10, 1, 1000, '🌱'), ('Basic', 'Good for small projects', 2, 1, 10, 1, 2000, '📦'), ('Standard', 'Balanced resources for most uses', 2, 2, 20, 7, 3000, '⚙️'), ('Pro', 'More power for demanding apps', 4, 2, 40, 7, 5000, '🚀'), ('Premium', 'Maximum performance', 8, 4, 80, 30, 10000, '💎')]
            for name, desc, ram, cpu, disk, days, cost, icon in default_deploy_plans:
                cur.execute('INSERT INTO deploy_plans \n                           (name, description, ram_gb, cpu_cores, disk_gb, duration_days, cost_coins, icon, created_at)\n                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', (name, desc, ram, cpu, disk, days, cost, icon, datetime.now().isoformat()))
        cur.execute('SELECT COUNT(*) as count FROM resource_plans')
        if cur.fetchone()['count'] == 0:
            default_resource_plans = [('Micro', 'Minimal resources', 1, 1, 10, 500, '🔹'), ('Small', 'Light workloads', 2, 1, 20, 1000, '🔸'), ('Medium', 'Balanced performance', 4, 2, 40, 2000, '⚡'), ('Large', 'Heavy workloads', 8, 4, 80, 4000, '🔥'), ('XLarge', 'Maximum power', 16, 8, 160, 8000, '💫')]
            for name, desc, ram, cpu, disk, cost, icon in default_resource_plans:
                cur.execute('INSERT INTO resource_plans \n                           (name, description, ram_gb, cpu_cores, disk_gb, upgrade_cost, icon, created_at)\n                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)', (name, desc, ram, cpu, disk, cost, icon, datetime.now().isoformat()))
        coin_settings = [('coins_per_invite', '50'), ('coins_per_message', '1'), ('coins_per_voice_minute', '2'), ('coins_daily_reward', '100'), ('coins_vps_renewal_1day', '50'), ('coins_vps_renewal_7days', '300'), ('coins_vps_renewal_30days', '1000'), ('default_vps_duration_days', '7'), ('vps_expiry_warning_hours', '24'), ('message_cooldown_seconds', '60'), ('voice_min_duration_minutes', '5'), ('leaderboard_top_count', '10'), ('coins_bonus_multiplier', '1.0'), ('streak_bonus_multiplier', '0.1'), ('max_streak_bonus', '2.0'), ('quest_refresh_hours', '24'), ('shop_booster_2x_1hour', '200'), ('shop_booster_2x_24hour', '1500'), ('shop_username_color', '1000'), ('shop_custom_role', '2000')]
        for key, value in coin_settings:
            cur.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', (key, value))
        cur.execute('CREATE TABLE IF NOT EXISTS achievements (\n        id INTEGER PRIMARY KEY AUTOINCREMENT,\n        name TEXT UNIQUE NOT NULL,\n        description TEXT NOT NULL,\n        requirement_type TEXT NOT NULL,\n        requirement_value INTEGER NOT NULL,\n        reward_coins INTEGER NOT NULL,\n        icon TEXT DEFAULT \'🏆\',\n        category TEXT DEFAULT \'general\'\n    )')
        cur.execute('CREATE TABLE IF NOT EXISTS user_achievements (\n        id INTEGER PRIMARY KEY AUTOINCREMENT,\n        user_id TEXT NOT NULL,\n        achievement_id INTEGER NOT NULL,\n        unlocked_at TEXT NOT NULL,\n        FOREIGN KEY (achievement_id) REFERENCES achievements(id)\n    )')
        cur.execute('CREATE TABLE IF NOT EXISTS user_streaks (\n        user_id TEXT PRIMARY KEY,\n        current_streak INTEGER DEFAULT 0,\n        longest_streak INTEGER DEFAULT 0,\n        last_claim_date TEXT,\n        streak_bonus_multiplier REAL DEFAULT 1.0\n    )')
        cur.execute('CREATE TABLE IF NOT EXISTS quests (\n        id INTEGER PRIMARY KEY AUTOINCREMENT,\n        name TEXT NOT NULL,\n        description TEXT NOT NULL,\n        quest_type TEXT NOT NULL,\n        requirement_type TEXT NOT NULL,\n        requirement_value INTEGER NOT NULL,\n        reward_coins INTEGER NOT NULL,\n        duration TEXT DEFAULT \'daily\',\n        active INTEGER DEFAULT 1\n    )')
        cur.execute('CREATE TABLE IF NOT EXISTS user_quests (\n        id INTEGER PRIMARY KEY AUTOINCREMENT,\n        user_id TEXT NOT NULL,\n        quest_id INTEGER NOT NULL,\n        progress INTEGER DEFAULT 0,\n        completed INTEGER DEFAULT 0,\n        started_at TEXT NOT NULL,\n        completed_at TEXT,\n        FOREIGN KEY (quest_id) REFERENCES quests(id)\n    )')
        cur.execute('CREATE TABLE IF NOT EXISTS shop_items (\n        id INTEGER PRIMARY KEY AUTOINCREMENT,\n        name TEXT UNIQUE NOT NULL,\n        description TEXT NOT NULL,\n        price INTEGER NOT NULL,\n        item_type TEXT NOT NULL,\n        item_data TEXT,\n        stock INTEGER DEFAULT -1,\n        purchasable INTEGER DEFAULT 1,\n        icon TEXT DEFAULT \'🛒\'\n    )')
        cur.execute('CREATE TABLE IF NOT EXISTS user_purchases (\n        id INTEGER PRIMARY KEY AUTOINCREMENT,\n        user_id TEXT NOT NULL,\n        item_id INTEGER NOT NULL,\n        purchased_at TEXT NOT NULL,\n        expires_at TEXT,\n        active INTEGER DEFAULT 1,\n        FOREIGN KEY (item_id) REFERENCES shop_items(id)\n    )')
        cur.execute('CREATE TABLE IF NOT EXISTS active_boosters (\n        id INTEGER PRIMARY KEY AUTOINCREMENT,\n        user_id TEXT NOT NULL,\n        booster_type TEXT NOT NULL,\n        multiplier REAL NOT NULL,\n        activated_at TEXT NOT NULL,\n        expires_at TEXT NOT NULL,\n        active INTEGER DEFAULT 1\n    )')
        cur.execute('CREATE TABLE IF NOT EXISTS coin_gifts (\n        id INTEGER PRIMARY KEY AUTOINCREMENT,\n        sender_id TEXT NOT NULL,\n        receiver_id TEXT NOT NULL,\n        amount INTEGER NOT NULL,\n        message TEXT,\n        sent_at TEXT NOT NULL\n    )')
        cur.execute('CREATE TABLE IF NOT EXISTS referrals (\n        id INTEGER PRIMARY KEY AUTOINCREMENT,\n        referrer_id TEXT NOT NULL,\n        referred_id TEXT NOT NULL,\n        referral_code TEXT,\n        bonus_earned INTEGER DEFAULT 0,\n        created_at TEXT NOT NULL\n    )')
        cur.execute('CREATE TABLE IF NOT EXISTS lottery_tickets (\n        id INTEGER PRIMARY KEY AUTOINCREMENT,\n        user_id TEXT NOT NULL,\n        ticket_number INTEGER NOT NULL,\n        draw_id INTEGER NOT NULL,\n        purchased_at TEXT NOT NULL,\n        won INTEGER DEFAULT 0\n    )')
        cur.execute('CREATE TABLE IF NOT EXISTS user_jobs (\n        user_id TEXT PRIMARY KEY,\n        current_job TEXT,\n        job_level INTEGER DEFAULT 1,\n        job_experience INTEGER DEFAULT 0,\n        last_work_time TEXT,\n        total_work_count INTEGER DEFAULT 0\n    )')
        default_achievements = [('First Steps', 'Earn your first coin', 'coins_earned', 1, 50, '🎯', 'beginner'), ('Chatterbox', 'Send 100 messages', 'messages', 100, 100, '💬', 'social'), ('Voice Master', 'Spend 60 minutes in voice', 'voice_minutes', 60, 150, '🎤', 'social'), ('Inviter', 'Invite 5 members', 'invites', 5, 200, '👥', 'social'), ('Rich', 'Accumulate 1000 coins', 'balance', 1000, 500, '💰', 'wealth'), ('Millionaire', 'Accumulate 10000 coins', 'balance', 10000, 2000, '💎', 'wealth'), ('Dedicated', 'Maintain a 7-day streak', 'streak', 7, 300, '🔥', 'dedication'), ('Loyal', 'Maintain a 30-day streak', 'streak', 30,1000, '🏆', 'dedication')]
        for name, desc, req_type, req_val, reward, icon, category in default_achievements:
            cur.execute('INSERT OR IGNORE INTO achievements \n                       (name, description, requirement_type, requirement_value, reward_coins, icon, category)\n                       VALUES (?, ?, ?, ?, ?, ?, ?)', (name, desc, req_type, req_val, reward, icon, category))
        default_quests = [('Daily Chatter', 'Send 20 messages today', 'daily', 'messages', 20, 50), ('Voice Time', 'Spend 30 minutes in voice today', 'daily', 'voice_minutes', 30, 75), ('Social Butterfly', 'Invite 1 member today', 'daily', 'invites', 1, 100), ('Weekly Grind', 'Send 100 messages this week', 'weekly', 'messages', 100, 200), ('Voice Champion', 'Spend 3 hours in voice this week', 'weekly', 'voice_minutes', 180, 300)]
        for name, desc, duration, req_type, req_val, reward in default_quests:
            cur.execute('INSERT OR IGNORE INTO quests \n                       (name, description, quest_type, requirement_type, requirement_value, reward_coins, duration)\n                       VALUES (?, ?, ?, ?, ?, ?, ?)', (name, desc, duration, req_type, req_val, reward, duration))
        default_shop_items = [('2x Coin Booster (1 Hour)', 'Double coin earnings for 1 hour', 200, 'booster', '{\"multiplier\":2.0,\"duration\":3600}', (-1), '⚡'), ('2x Coin Booster (24 Hours)', 'Double coin earnings for 24 hours', 1500, 'booster', '{\"multiplier\":2.0,\"duration\":86400}', (-1), '🚀'), ('3x Coin Booster (1 Hour)', 'Triple coin earnings for 1 hour', 500, 'booster', '{\"multiplier\":3.0,\"duration\":3600}', (-1), '💫'), ('Custom Username Color', 'Get a custom colored username', 1000, 'cosmetic', '{\"type\":\"color\"}', (-1), '🎨'), ('Custom Role', 'Get a custom role with your name', 2000, 'cosmetic', '{\"type\":\"role\"}', (-1), '👑'), ('Lottery Ticket', 'Enter the weekly lottery draw', 50, 'lottery', '{\"type\":\"ticket\"}', (-1), '�')]
        for name, desc, price, item_type, item_data, stock, icon in default_shop_items:
            cur.execute('INSERT OR IGNORE INTO shop_items \n                       (name, description, price, item_type, item_data, stock, icon)\n                       VALUES (?, ?, ?, ?, ?, ?, ?)', (name, desc, price, item_type, item_data, stock, icon))
        cur.execute('PRAGMA table_info(vps)')
        vps_columns = [col[1] for col in cur.fetchall()]
        if 'expires_at' not in vps_columns:
            cur.execute('ALTER TABLE vps ADD COLUMN expires_at TEXT')
        if 'duration_days' not in vps_columns:
            cur.execute('ALTER TABLE vps ADD COLUMN duration_days INTEGER DEFAULT 7')
        if 'auto_renew' not in vps_columns:
            cur.execute('ALTER TABLE vps ADD COLUMN auto_renew INTEGER DEFAULT 0')
        conn.commit()
        conn.close()
    def get_setting(key: str, default: Any=None):
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT value FROM settings WHERE key = ?', (key,))
        row = cur.fetchone()
        conn.close()
        if row:
            return row[0]
        else:
            return default
    def set_setting(key: str, value: str):
        conn = get_db()
        cur = conn.cursor()
        cur.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, value))
        conn.commit()
        conn.close()
    def get_nodes() -> List[Dict]:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT * FROM nodes')
        rows = cur.fetchall()
        conn.close()
        nodes = [dict(row) for row in rows]
        for node in nodes:
            node['tags'] = json.loads(node['tags'])
        return nodes
    def get_node(node_id: int) -> Optional[Dict]:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT * FROM nodes WHERE id = ?', (node_id,))
        row = cur.fetchone()
        conn.close()
        if row:
            node = dict(row)
            node['tags'] = json.loads(node['tags'])
            return node
    def get_current_vps_count(node_id: int) -> int:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT COUNT(*) FROM vps WHERE node_id = ?', (node_id,))
        count = cur.fetchone()[0]
        conn.close()
        return count
    def get_deploy_plans(active_only: bool=True) -> List[Dict]:
        """Get all deployment plans"""
        conn = get_db()
        cur = conn.cursor()
        if active_only:
            cur.execute('SELECT * FROM deploy_plans WHERE active = 1 ORDER BY cost_coins')
        else:
            cur.execute('SELECT * FROM deploy_plans ORDER BY cost_coins')
        rows = cur.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    def get_deploy_plan(plan_id: int) -> Dict:
        """Get a specific deployment plan"""
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT * FROM deploy_plans WHERE id = ?', (plan_id,))
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None
    def get_resource_plans(active_only: bool=True) -> List[Dict]:
        """Get all resource upgrade plans"""
        conn = get_db()
        cur = conn.cursor()
        if active_only:
            cur.execute('SELECT * FROM resource_plans WHERE active = 1 ORDER BY upgrade_cost')
        else:
            cur.execute('SELECT * FROM resource_plans ORDER BY upgrade_cost')
        rows = cur.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    def get_resource_plan(plan_id: int) -> Dict:
        """Get a specific resource plan"""
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT * FROM resource_plans WHERE id = ?', (plan_id,))
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None
    def log_vps_upgrade(vps_id: int, user_id: str, old_specs: Dict, new_specs: Dict, cost: int, upgraded_by: str=None):
        """Log VPS upgrade to history"""
        conn = get_db()
        cur = conn.cursor()
        cur.execute('INSERT INTO vps_upgrades \n                   (vps_id, user_id, old_ram, old_cpu, old_disk, new_ram, new_cpu, new_disk, cost_coins, upgraded_at, upgraded_by)\n                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', (vps_id, user_id, old_specs.get('ram'), old_specs.get('cpu'), old_specs.get('disk'), new_specs.get('ram'), new_specs.get('cpu'), new_specs.get('disk'), cost, datetime.now().isoformat(), upgraded_by or user_id))
        conn.commit()
        conn.close()
    def get_coupon(code: str) -> Optional[Dict]:
        """Get coupon by code"""
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT * FROM coupon_codes WHERE code = ? COLLATE NOCASE', (code,))
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None
    def get_all_coupons(active_only: bool=False) -> List[Dict]:
        """Get all coupons"""
        conn = get_db()
        cur = conn.cursor()
        if active_only:
            cur.execute('SELECT * FROM coupon_codes WHERE active = 1 ORDER BY created_at DESC')
        else:
            cur.execute('SELECT * FROM coupon_codes ORDER BY created_at DESC')
        rows = cur.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    def create_coupon(code: str, coins: int, max_uses: int=None, expires_at: str=None, created_by: str=None, description: str=None) -> int:
        """Create a new coupon code"""
        conn = get_db()
        cur = conn.cursor()
        cur.execute('INSERT INTO coupon_codes \n                   (code, coins, max_uses, expires_at, created_by, created_at, description)\n                   VALUES (?, ?, ?, ?, ?, ?, ?)', (code.upper(), coins, max_uses, expires_at, created_by, datetime.now().isoformat(), description))
        coupon_id = cur.lastrowid
        conn.commit()
        conn.close()
        return coupon_id
    def redeem_coupon(code: str, user_id: str):
        # irreducible cflow, using cdg fallback
        """Redeem a coupon code - Returns (success, message, coins)"""
        conn = None
        conn = get_db()
        conn.execute('PRAGMA busy_timeout = 5000')
        cur = conn.cursor()
        cur.execute('SELECT * FROM coupon_codes WHERE code = ? COLLATE NOCASE', (code,))
        coupon = cur.fetchone()
        if not coupon:
            if conn:
                conn.close()
            coupon = dict(coupon)
            if not coupon['active']:
                return (False, 'This coupon has been disabled', 0)
                if coupon['expires_at']:
                    expiry = datetime.fromisoformat(coupon['expires_at'])
                    if datetime.now() > expiry:
                        return (False, 'This coupon has expired', 0)
                        if coupon['max_uses'] is not None and coupon['current_uses'] >= coupon['max_uses']:
                                return (False, 'This coupon has reached its usage limit', 0)
                                cur.execute('SELECT * FROM coupon_redemptions WHERE coupon_id = ? AND user_id = ?', (coupon['id'], user_id))
                                if cur.fetchone():
                                    return (False, 'You have already redeemed this coupon', 0)
                                    coins = coupon['coins']
                                    cur.execute('INSERT OR IGNORE INTO user_coins (user_id, balance, total_earned, total_spent, created_at)\n                       VALUES (?, 0, 0, 0, ?)', (user_id, datetime.now().isoformat()))
                                    cur.execute('UPDATE user_coins \n                       SET balance = balance + ?, total_earned = total_earned + ?\n                       WHERE user_id = ?', (coins, coins, user_id))
                                    cur.execute('INSERT INTO coin_transactions \n                       (user_id, amount, type, description, created_at)\n                       VALUES (?, ?, ?, ?, ?)', (user_id, coins, 'coupon_redeem', f'Redeemed coupon: {code}', datetime.now().isoformat()))
                                    cur.execute('INSERT INTO coupon_redemptions \n                       (coupon_id, user_id, coins_received, redeemed_at)\n                       VALUES (?, ?, ?, ?)', (coupon['id'], user_id, coins, datetime.now().isoformat()))
                                    cur.execute('UPDATE coupon_codes SET current_uses = current_uses + 1 WHERE id = ?', (coupon['id'],))
                                    conn.commit()
                                    match (True, 'Coupon redeemed successfully', coins):
                                        if conn:
                                            conn.close()
                                        except Exception as e:
                                                logger.error(f'Error redeeming coupon {code}: {e}')
                                                if conn:
                                                    conn.rollback()
                                                return (False, f'An error occurred: {str(e)}', 0)
    def get_coupon_stats(coupon_id: int) -> Dict:
        """Get coupon usage statistics"""
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT * FROM coupon_codes WHERE id = ?', (coupon_id,))
        coupon = cur.fetchone()
        if not coupon:
            conn.close()
            return
        else:
            coupon = dict(coupon)
            cur.execute('SELECT COUNT(*) as count FROM coupon_redemptions WHERE coupon_id = ?', (coupon_id,))
            redemptions = cur.fetchone()['count']
            cur.execute('SELECT SUM(coins_received) as total FROM coupon_redemptions WHERE coupon_id = ?', (coupon_id,))
            total_coins = cur.fetchone()['total'] or 0
            cur.execute('SELECT user_id, coins_received, redeemed_at \n                   FROM coupon_redemptions \n                   WHERE coupon_id = ? \n                   ORDER BY redeemed_at DESC LIMIT 10', (coupon_id,))
            recent = [dict(row) for row in cur.fetchall()]
            conn.close()
            return {'coupon': coupon, 'redemptions': redemptions, 'total_coins': total_coins, 'recent': recent}
    def get_vps_data() -> Dict[str, List[Dict[str, Any]]]:
        cur = conn.cursor()
        cur.execute('INSERT INTO vps_upgrades \n                   (vps_id, user_id, old_ram, old_cpu, old_disk, new_ram, new_cpu, new_disk, cost_coins, upgraded_at, upgraded_by)\n                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', (vps_id, user_id, old_specs['ram'], old_specs['cpu'], old_specs['disk'], new_specs['ram'], new_specs['cpu'], new_specs['disk'], cost, datetime.now().isoformat(), upgraded_by))
        conn.commit()
        conn.close()
    def get_vps_data() -> Dict[str, List[Dict[str, Any]]]:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT * FROM vps')
        rows = cur.fetchall()
        conn.close()
        data = {}
        for row in rows:
            user_id = row['user_id']
            if user_id not in data:
                data[user_id] = []
            vps = dict(row)
            vps['shared_with'] = json.loads(vps['shared_with'])
            vps['suspension_history'] = json.loads(vps['suspension_history'])
            vps['suspended'] = bool(vps['suspended'])
            vps['whitelisted'] = bool(vps['whitelisted'])
            vps['os_version'] = vps.get('os_version', 'ubuntu:22.04')
            data[user_id].append(vps)
        return data
    def get_admins() -> List[str]:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT user_id FROM admins')
        rows = cur.fetchall()
        conn.close()
        return [row['user_id'] for row in rows]
    def save_vps_data():
        conn = get_db()
        cur = conn.cursor()
        for user_id, vps_list in vps_data.items():
            for vps in vps_list:
                shared_json = json.dumps(vps['shared_with'])
                history_json = json.dumps(vps['suspension_history'])
                suspended_int = 1 if vps['suspended'] else 0
                whitelisted_int = 1 if vps.get('whitelisted', False) else 0
                os_ver = vps.get('os_version', 'ubuntu:22.04')
                created_at = vps.get('created_at', datetime.now().isoformat())
                node_id = vps.get('node_id', 1)
                if 'id' not in vps or vps['id'] is None:
                    cur.execute('INSERT INTO vps (user_id, node_id, container_name, ram, cpu, storage, config, os_version, status, suspended, whitelisted, created_at, shared_with, suspension_history)\n                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', (user_id, node_id, vps['container_name'], vps['ram'], vps['cpu'], vps['storage'], vps['config'], os_ver, vps['status'], suspended_int, whitelisted_int, created_at, shared_json, history_json))
                    vps['id'] = cur.lastrowid
                else:
                    cur.execute('UPDATE vps SET user_id = ?, node_id = ?, container_name = ?, ram = ?, cpu = ?, storage = ?, config = ?, os_version = ?, status = ?, suspended = ?, whitelisted = ?, shared_with = ?, suspension_history = ?\n                               WHERE id = ?', (user_id, node_id, vps['container_name'], vps['ram'], vps['cpu'], vps['storage'], vps['config'], os_ver, vps['status'], suspended_int, whitelisted_int, shared_json, history_json, vps['id']))
        conn.commit()
        conn.close()
    def save_admin_data():
        conn = get_db()
        cur = conn.cursor()
        cur.execute('DELETE FROM admins')
        for admin_id in admin_data['admins']:
            cur.execute('INSERT INTO admins (user_id) VALUES (?)', (admin_id,))
        conn.commit()
        conn.close()
    def get_user_allocation(user_id: str) -> int:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT allocated_ports FROM port_allocations WHERE user_id = ?', (user_id,))
        row = cur.fetchone()
        conn.close()
        return row[0] if row else 0
    def get_user_used_ports(user_id: str) -> int:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT COUNT(*) FROM port_forwards WHERE user_id = ?', (user_id,))
        row = cur.fetchone()
        conn.close()
        return row[0]
    def allocate_ports(user_id: str, amount: int):
        conn = get_db()
        cur = conn.cursor()
        cur.execute('INSERT OR REPLACE INTO port_allocations (user_id, allocated_ports) VALUES (?, COALESCE((SELECT allocated_ports FROM port_allocations WHERE user_id = ?), 0) + ?)', (user_id, user_id, amount))
        conn.commit()
        conn.close()
    def deallocate_ports(user_id: str, amount: int):
        conn = get_db()
        cur = conn.cursor()
        cur.execute('UPDATE port_allocations SET allocated_ports = GREATEST(0, allocated_ports - ?) WHERE user_id = ?', (amount, user_id))
        conn.commit()
        conn.close()
    def get_available_host_port(node_id: int) -> Optional[int]:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT host_port FROM port_forwards WHERE vps_container IN (SELECT container_name FROM vps WHERE node_id = ?)', (node_id,))
        used_ports = set((row[0] for row in cur.fetchall()))
        conn.close()
        for _ in range(100):
            port = random.randint(20000, 50000)
            if port not in used_ports:
                return port
        return
    async def create_port_forward(user_id: str, container: str, vps_port: int, node_id: int) -> Optional[int]:
        host_port = get_available_host_port(node_id)
        if not host_port:
            return
        else:
            try:
                await execute_lxc(container, f'config device add {container} tcp_proxy_{host_port} proxy listen=tcp:0.0.0.0:{host_port} connect=tcp:127.0.0.1:{vps_port}', node_id=node_id)
                await execute_lxc(container, f'config device add {container} udp_proxy_{host_port} proxy listen=udp:0.0.0.0:{host_port} connect=udp:127.0.0.1:{vps_port}', node_id=node_id)
                conn = get_db()
                cur = conn.cursor()
                cur.execute('INSERT INTO port_forwards (user_id, vps_container, vps_port, host_port, created_at) VALUES (?, ?, ?, ?, ?)', (user_id, container, vps_port, host_port, datetime.now().isoformat()))
                conn.commit()
                conn.close()
                return host_port
            except Exception as e:
                logger.error(f'Failed to create port forward: {e}')
                return
    async def remove_port_forward(forward_id: int, is_admin: bool=False):
        """Remove a port forward - Returns (success, error_message)"""
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT user_id, vps_container, host_port FROM port_forwards WHERE id = ?', (forward_id,))
        row = cur.fetchone()
        if not row:
            conn.close()
            return (False, None)
        else:
            user_id, container, host_port = row
            node_id = find_node_id_for_container(container)
            try:
                await execute_lxc(container, f'config device remove {container} tcp_proxy_{host_port}', node_id=node_id)
                await execute_lxc(container, f'config device remove {container} udp_proxy_{host_port}', node_id=node_id)
                cur.execute('DELETE FROM port_forwards WHERE id = ?', (forward_id,))
                conn.commit()
                conn.close()
                return (True, user_id)
            except Exception as e:
                logger.error(f'Failed to remove port forward {forward_id}: {e}')
                conn.close()
                return (False, None)
    def get_user_forwards(user_id: str) -> List[Dict]:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT * FROM port_forwards WHERE user_id = ? ORDER BY created_at DESC', (user_id,))
        rows = cur.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    async def recreate_port_forwards(container_name: str) -> int:
        node_id = find_node_id_for_container(container_name)
        readded_count = 0
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT vps_port, host_port FROM port_forwards WHERE vps_container = ?', (container_name,))
        rows = cur.fetchall()
        for row in rows:
            vps_port = row['vps_port']
            host_port = row['host_port']
            try:
                await execute_lxc(container_name, f'config device add {container_name} tcp_proxy_{host_port} proxy listen=tcp:0.0.0.0:{host_port} connect=tcp:127.0.0.1:{vps_port}', node_id=node_id)
                await execute_lxc(container_name, f'config device add {container_name} udp_proxy_{host_port} proxy listen=udp:0.0.0.0:{host_port} connect=udp:127.0.0.1:{vps_port}', node_id=node_id)
                logger.info(f'Re-added port forward {host_port}->{vps_port} for {container_name}')
                readded_count += 1
            except Exception as e:
                logger.error(f'Failed to re-add port forward {host_port}->{vps_port} for {container_name}: {e}')
                pass
            else:
                pass
        conn.close()
        return readded_count
    def find_node_id_for_container(container_name: str) -> int:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT node_id FROM vps WHERE container_name = ?', (container_name,))
        row = cur.fetchone()
        conn.close()
        return row[0] if row else 1
    def get_user_coins(user_id: str) -> Dict:
        """Get user\'s coin balance and stats"""
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT * FROM user_coins WHERE user_id = ?', (user_id,))
        row = cur.fetchone()
        conn.close()
        if row:
            return dict(row)
        else:
            conn = get_db()
            cur = conn.cursor()
            cur.execute('INSERT INTO user_coins (user_id, balance, total_earned, total_spent, created_at)\n                       VALUES (?, 0, 0, 0, ?)', (user_id, datetime.now().isoformat()))
            conn.commit()
            conn.close()
            return {'user_id': user_id, 'balance': 0, 'total_earned': 0, 'total_spent': 0, 'invite_count': 0, 'message_count': 0, 'voice_minutes': 0}
    def add_coins(user_id: str, amount: int, transaction_type: str, description: str=None) -> int:
        """Add coins to user\'s balance and log transaction"""
        conn = get_db()
        cur = conn.cursor()
        cur.execute('INSERT OR IGNORE INTO user_coins (user_id, balance, total_earned, total_spent, created_at)\n                   VALUES (?, 0, 0, 0, ?)', (user_id, datetime.now().isoformat()))
        cur.execute('UPDATE user_coins \n                   SET balance = balance + ?, total_earned = total_earned + ?\n                   WHERE user_id = ?', (amount, amount, user_id))
        cur.execute('INSERT INTO coin_transactions (user_id, amount, type, description, created_at)\n                   VALUES (?, ?, ?, ?, ?)', (user_id, amount, transaction_type, description, datetime.now().isoformat()))
        cur.execute('SELECT balance FROM user_coins WHERE user_id = ?', (user_id,))
        new_balance = cur.fetchone()[0]
        conn.close()
        return new_balance
    def remove_coins(user_id: str, amount: int, transaction_type: str, description: str=None):
        """Remove coins from user\'s balance. Returns (success, new_balance)"""
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT balance FROM user_coins WHERE user_id = ?', (user_id,))
        row = cur.fetchone()
        if not row or row[0] < amount:
            conn.close()
            return (False, row[0] if row else 0)
        else:
            cur.execute('UPDATE user_coins \n                   SET balance = balance - ?, total_spent = total_spent + ?\n                   WHERE user_id = ?', (amount, amount, user_id))
            cur.execute('INSERT INTO coin_transactions (user_id, amount, type, description, created_at)\n                   VALUES (?, ?, ?, ?, ?)', (user_id, -amount, transaction_type, description, datetime.now().isoformat()))
            conn.commit()
            cur.execute('SELECT balance FROM user_coins WHERE user_id = ?', (user_id,))
            new_balance = cur.fetchone()[0]
            conn.close()
            return (True, new_balance)
    def get_coin_leaderboard(limit: int=10) -> List[Dict]:
        """Get top users by coin balance"""
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT user_id, balance, total_earned, invite_count, message_count, voice_minutes\n                   FROM user_coins \n                   ORDER BY balance DESC \n                   LIMIT ?', (limit,))
        rows = cur.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    def get_user_transactions(user_id: str, limit: int=10) -> List[Dict]:
        """Get user\'s recent transactions"""
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT * FROM coin_transactions \n                   WHERE user_id = ? \n                   ORDER BY created_at DESC \n                   LIMIT ?', (user_id, limit))
        rows = cur.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    def set_vps_expiration(vps_id: int, duration_days: int):
        """Set VPS expiration date"""
        expires_at = datetime.now() + timedelta(days=duration_days)
        conn = get_db()
        cur = conn.cursor()
        cur.execute('UPDATE vps \n                   SET expires_at = ?, duration_days = ?\n                   WHERE id = ?', (expires_at.isoformat(), duration_days, vps_id))
        conn.commit()
        conn.close()
    def get_expiring_vps(hours_before: int=24) -> List[Dict]:
        """Get VPS that will expire soon"""
        warning_time = datetime.now() + timedelta(hours=hours_before)
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT * FROM vps \n                   WHERE expires_at IS NOT NULL \n                   AND expires_at <= ? \n                   AND suspended = 0\n                   AND whitelisted = 0\n                   ORDER BY expires_at ASC', (warning_time.isoformat(),))
        rows = cur.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    def renew_vps(vps_id: int, duration_days: int) -> bool:
        """Renew VPS for additional days"""
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT expires_at FROM vps WHERE id = ?', (vps_id,))
        row = cur.fetchone()
        if not row:
            conn.close()
            return False
        else:
            current_expiry = row[0]
            if current_expiry:
                base_time = datetime.fromisoformat(current_expiry)
                if base_time < datetime.now():
                    base_time = datetime.now()
            else:
                base_time = datetime.now()
            new_expiry = base_time + timedelta(days=duration_days)
            cur.execute('UPDATE vps \n                   SET expires_at = ?, duration_days = duration_days + ?\n                   WHERE id = ?', (new_expiry.isoformat(), duration_days, vps_id))
            conn.commit()
            conn.close()
            return True
    def check_and_suspend_expired_vps():
        """Check for expired VPS and suspend them"""
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT id, user_id, container_name, expires_at \n                   FROM vps \n                   WHERE expires_at IS NOT NULL \n                   AND expires_at <= ? \n                   AND suspended = 0\n                   AND whitelisted = 0\n                   AND status = \'running\' ', (datetime.now().isoformat(),))
        expired_vps = cur.fetchall()
        conn.close()
        suspended_count = 0
        for vps in expired_vps:
            vps_id, user_id, container_name, expires_at = vps
            node_id = find_node_id_for_container(container_name)
            try:
                asyncio.create_task(execute_lxc(container_name, f'stop {container_name}', node_id=node_id))
                conn = get_db()
                cur = conn.cursor()
                cur.execute('UPDATE vps \n                           SET suspended = 1, status = \'stopped\'\n                           WHERE id = ?', (vps_id,))
                cur.execute('SELECT suspension_history FROM vps WHERE id = ?', (vps_id,))
                history = json.loads(cur.fetchone()[0] or '[]')
                history.append({'time': datetime.now().isoformat(), 'reason': f'VPS expired (was valid until {expires_at})', 'by': 'Auto-Suspension System'})
                cur.execute('UPDATE vps SET suspension_history = ? WHERE id = ?', (json.dumps(history), vps_id))
                conn.commit()
                conn.close()
                suspended_count += 1
                logger.info(f'Auto-suspended expired VPS: {container_name} (user: {user_id})')
            except Exception as e:
                logger.error(f'Failed to suspend expired VPS {container_name}: {e}')
        return suspended_count
    def format_expiry_time(expires_at_str: str) -> Dict:
        """Format expiry time into human-readable format with status"""
        if not expires_at_str:
            return {'text': '♾️ Never', 'status': 'permanent', 'color': 65416, 'emoji': '♾️', 'hours_left': float('inf')}
        else:
            expires_at = datetime.fromisoformat(expires_at_str)
            now = datetime.now()
            time_left = expires_at - now
            if time_left.total_seconds() <= 0:
                return {'text': '❌ EXPIRED', 'status': 'expired', 'color': 16711680, 'emoji': '❌', 'hours_left': 0}
            else:
                hours_left = time_left.total_seconds() / 3600
                days_left = time_left.days
                if days_left > 7:
                    status_text = f'✅ {days_left} days'
                    status = 'safe'
                    color = 65416
                    emoji = '✅'
                else:
                    if days_left > 1:
                        status_text = f'⚠️ {days_left} days'
                        status = 'warning'
                        color = 16755200
                        emoji = '⚠️'
                    else:
                        if hours_left > 1:
                            status_text = f'🚨 {int(hours_left)} hours'
                            status = 'critical'
                            color = 16737792
                            emoji = '🚨'
                        else:
                            minutes_left = int(time_left.total_seconds() / 60)
                            status_text = f'⏰ {minutes_left} minutes'
                            status = 'urgent'
                            color = 16711680
                            emoji = '⏰'
                return {'text': status_text, 'status': status, 'color': color, 'emoji': emoji, 'hours_left': hours_left, 'expires_at': expires_at.strftime('%Y-%m-%d %H:%M:%S')}
    def check_and_award_achievements(user_id: str):
        """Check if user unlocked any achievements"""
        conn = get_db()
        cur = conn.cursor()
        coins_data = get_user_coins(user_id)
        vps_count = len(vps_data.get(user_id, []))
        cur.execute('SELECT COUNT(*) FROM user_quests WHERE user_id = ? AND completed = 1', (user_id,))
        quests_completed = cur.fetchone()[0]
        cur.execute('SELECT COALESCE(SUM(amount), 0) FROM coin_gifts WHERE sender_id = ?', (user_id,))
        coins_gifted = cur.fetchone()[0]
        cur.execute('SELECT total_work_count FROM user_jobs WHERE user_id = ?', (user_id,))
        work_row = cur.fetchone()
        work_count = work_row[0] if work_row else 0
        cur.execute('SELECT current_streak FROM user_streaks WHERE user_id = ?', (user_id,))
        streak_row = cur.fetchone()
        current_streak = streak_row[0] if streak_row else 0
        cur.execute('SELECT * FROM achievements')
        achievements = cur.fetchall()
        newly_unlocked = []
        for achievement in achievements:
            ach_id = achievement['id']
            req_type = achievement['requirement_type']
            req_value = achievement['requirement_value']
            reward = achievement['reward_coins']
            cur.execute('SELECT id FROM user_achievements WHERE user_id = ? AND achievement_id = ?', (user_id, ach_id))
            if cur.fetchone():
                continue
            else:
                unlocked = False
                if req_type == 'coins_earned':
                    unlocked = coins_data['total_earned'] >= req_value
                else:
                    if req_type == 'messages':
                        unlocked = coins_data['message_count'] >= req_value
                    else:
                        if req_type == 'voice_minutes':
                            unlocked = coins_data['voice_minutes'] >= req_value
                        else:
                            if req_type == 'invites':
                                unlocked = coins_data['invite_count'] >= req_value
                            else:
                                if req_type == 'balance':
                                    unlocked = coins_data['balance'] >= req_value
                                else:
                                    if req_type == 'streak':
                                        unlocked = current_streak >= req_value
                                    else:
                                        if req_type == 'vps_count':
                                            unlocked = vps_count >= req_value
                                        else:
                                            if req_type == 'quests_completed':
                                                unlocked = quests_completed >= req_value
                                            else:
                                                if req_type == 'coins_gifted':
                                                    unlocked = coins_gifted >= req_value
                                                else:
                                                    if req_type == 'work_count':
                                                        unlocked = work_count >= req_value
                if unlocked:
                    cur.execute('INSERT INTO user_achievements (user_id, achievement_id, unlocked_at)\n                           VALUES (?, ?, ?)', (user_id, ach_id, datetime.now().isoformat()))
                    add_coins(user_id, reward, 'achievement', f"Achievement: {achievement['name']}")
                    newly_unlocked.append(dict(achievement))
        conn.commit()
        conn.close()
        return newly_unlocked
    def get_user_achievements(user_id: str) -> List[Dict]:
        """Get user\'s unlocked achievements"""
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT a.*, ua.unlocked_at \n                   FROM achievements a\n                   JOIN user_achievements ua ON a.id = ua.achievement_id\n                   WHERE ua.user_id = ?\n                   ORDER BY ua.unlocked_at DESC', (user_id,))
        rows = cur.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    def update_daily_streak(user_id: str) -> Dict:
        """Update user\'s daily streak"""
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT * FROM user_streaks WHERE user_id = ?', (user_id,))
        row = cur.fetchone()
        today = datetime.now().date().isoformat()
        if not row:
            cur.execute('INSERT INTO user_streaks \n                       (user_id, current_streak, longest_streak, last_claim_date, streak_bonus_multiplier)\n                       VALUES (?, 1, 1, ?, 1.0)', (user_id, today))
            conn.commit()
            conn.close()
            return {'current_streak': 1, 'longest_streak': 1, 'bonus_multiplier': 1.0}
        else:
            last_claim = row['last_claim_date']
            current_streak = row['current_streak']
            longest_streak = row['longest_streak']
            if last_claim == today:
                conn.close()
                return {'current_streak': current_streak, 'longest_streak': longest_streak, 'bonus_multiplier': row['streak_bonus_multiplier'], 'already_claimed': True}
            else:
                yesterday = (datetime.now().date() - timedelta(days=1)).isoformat()
                if last_claim == yesterday:
                    current_streak += 1
                    longest_streak = max(longest_streak, current_streak)
                else:
                    current_streak = 1
                streak_bonus = float(get_setting('streak_bonus_multiplier', 0.1))
                max_bonus = float(get_setting('max_streak_bonus', 2.0))
                bonus_multiplier = min(1.0 + current_streak * streak_bonus, max_bonus)
                cur.execute('UPDATE user_streaks \n                   SET current_streak = ?, longest_streak = ?, last_claim_date = ?, \n                       streak_bonus_multiplier = ?\n                   WHERE user_id = ?', (current_streak, longest_streak, today, bonus_multiplier, user_id))
                conn.commit()
                conn.close()
                return {'current_streak': current_streak, 'longest_streak': longest_streak, 'bonus_multiplier': bonus_multiplier}
    def get_active_quests(user_id: str, quest_type: str='daily') -> List[Dict]:
        """Get user\'s active quests"""
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT q.*, uq.progress, uq.completed, uq.id as user_quest_id\n                   FROM quests q\n                   LEFT JOIN user_quests uq ON q.id = uq.quest_id AND uq.user_id = ?\n                   WHERE q.duration = ? AND q.active = 1', (user_id, quest_type))
        quests = [dict(row) for row in cur.fetchall()]
        for quest in quests:
            if quest['user_quest_id'] is None:
                cur.execute('INSERT INTO user_quests (user_id, quest_id, progress, started_at)\n                           VALUES (?, ?, 0, ?)', (user_id, quest['id'], datetime.now().isoformat()))
                quest['progress'] = 0
                quest['completed'] = 0
        conn.commit()
        conn.close()
        return quests
    def update_quest_progress(user_id: str, requirement_type: str, amount: int=1):
        """Update progress for relevant quests"""
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT uq.id, uq.progress, q.requirement_value, q.reward_coins, q.name\n                   FROM user_quests uq\n                   JOIN quests q ON uq.quest_id = q.id\n                   WHERE uq.user_id = ? AND q.requirement_type = ? AND uq.completed = 0', (user_id, requirement_type))
        quests = cur.fetchall()
        completed_quests = []
        for quest in quests:
            quest_id, progress, req_value, reward, name = quest
            new_progress = progress + amount
            if new_progress >= req_value and progress < req_value:
                cur.execute('UPDATE user_quests \n                           SET progress = ?, completed = 1, completed_at = ?\n                           WHERE id = ?', (new_progress, datetime.now().isoformat(), quest_id))
                add_coins(user_id, reward, 'quest', f'Quest completed: {name}')
                completed_quests.append(name)
            else:
                cur.execute('UPDATE user_quests SET progress = ? WHERE id = ?', (new_progress, quest_id))
        conn.commit()
        conn.close()
        return completed_quests
    def get_active_booster(user_id: str) -> Optional[Dict]:
        """Get user\'s active booster"""
        conn = get_db()
        cur = conn.cursor()
        cur.execute('UPDATE active_boosters \n                   SET active = 0 \n                   WHERE expires_at <= ? AND active = 1', (datetime.now().isoformat(),))
        cur.execute('SELECT * FROM active_boosters \n                   WHERE user_id = ? AND active = 1 \n                   ORDER BY expires_at DESC LIMIT 1', (user_id,))
        row = cur.fetchone()
        conn.commit()
        conn.close()
        return dict(row) if row else None
    def activate_booster(user_id: str, multiplier: float, duration_seconds: int, booster_type: str='coins'):
        """Activate a coin booster"""
        expires_at = datetime.now() + timedelta(seconds=duration_seconds)
        conn = get_db()
        cur = conn.cursor()
        cur.execute('INSERT INTO active_boosters \n                   (user_id, booster_type, multiplier, activated_at, expires_at, active)\n                   VALUES (?, ?, ?, ?, ?, 1)', (user_id, booster_type, multiplier, datetime.now().isoformat(), expires_at.isoformat()))
        conn.commit()
        conn.close()
    def apply_booster_multiplier(user_id: str, base_amount: int) -> int:
        """Apply active booster to coin amount"""
        booster = get_active_booster(user_id)
        if booster:
            return int(base_amount * booster['multiplier'])
        else:
            return base_amount
    def get_shop_items(item_type: str=None) -> List[Dict]:
        """Get available shop items"""
        conn = get_db()
        cur = conn.cursor()
        if item_type:
            cur.execute('SELECT * FROM shop_items WHERE purchasable = 1 AND item_type = ? ORDER BY price', (item_type,))
        else:
            cur.execute('SELECT * FROM shop_items WHERE purchasable = 1 ORDER BY item_type, price')
        rows = cur.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    def purchase_item(user_id: str, item_id: int):
        """Purchase an item from the shop - Returns (success, message, item_data)"""
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT * FROM shop_items WHERE id = ?', (item_id,))
        item = cur.fetchone()
        if not item:
            conn.close()
            return (False, 'Item not found', None)
        else:
            if not item['purchasable']:
                conn.close()
                return (False, 'Item not available for purchase', None)
            else:
                if item['stock']!= (-1) and item['stock'] <= 0:
                    conn.close()
                    return (False, 'Item out of stock', None)
                else:
                    coins_data = get_user_coins(user_id)
                    if coins_data['balance'] < item['price']:
                        conn.close()
                        return (False, f"Insufficient coins. Need {item['price']:,}, have {coins_data['balance']:,}", None)
                    else:
                        success, new_balance = remove_coins(user_id, item['price'], 'shop_purchase', f"Purchased: {item['name']}")
                        if not success:
                            conn.close()
                            return (False, 'Payment failed', None)
                        else:
                            cur.execute('INSERT INTO user_purchases (user_id, item_id, purchased_at, active)\n                   VALUES (?, ?, ?, 1)', (user_id, item_id, datetime.now().isoformat()))
                            if item['stock']!= (-1):
                                cur.execute('UPDATE shop_items SET stock = stock - 1 WHERE id = ?', (item_id,))
                            conn.commit()
                            conn.close()
                            return (True, 'Purchase successful', dict(item))
    def gift_coins(sender_id: str, receiver_id: str, amount: int, message: str=None):
        """Gift coins to another user - Returns (success, message)"""
        if sender_id == receiver_id:
            return (False, 'You cannot gift coins to yourself')
        else:
            if amount <= 0:
                return (False, 'Amount must be positive')
            else:
                sender_coins = get_user_coins(sender_id)
                if sender_coins['balance'] < amount:
                    return (False, f"Insufficient coins. You have {sender_coins['balance']:,} coins")
                else:
                    success, _ = remove_coins(sender_id, amount, 'gift_sent', f'Gift to user {receiver_id}')
                    if not success:
                        return (False, 'Transfer failed')
                    else:
                        add_coins(receiver_id, amount, 'gift_received', f'Gift from user {sender_id}')
                        conn = get_db()
                        cur = conn.cursor()
                        cur.execute('INSERT INTO coin_gifts (sender_id, receiver_id, amount, message, sent_at)\n                   VALUES (?, ?, ?, ?, ?)', (sender_id, receiver_id, amount, message, datetime.now().isoformat()))
                        conn.commit()
                        conn.close()
                        return (True, f'Successfully gifted {amount:,} coins')
    def work_for_coins(user_id: str):
        """Work to earn coins (cooldown applies)"""
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT * FROM user_jobs WHERE user_id = ?', (user_id,))
        job_data = cur.fetchone()
        if not job_data:
            cur.execute('INSERT INTO user_jobs (user_id, current_job, job_level, last_work_time)\n                       VALUES (?, \'Beginner\', 1, NULL)', (user_id,))
            conn.commit()
            job_data = {'current_job': 'Beginner', 'job_level': 1, 'last_work_time': None, 'job_experience': 0, 'total_work_count': 0}
        else:
            job_data = dict(job_data)
        if job_data['last_work_time']:
            last_work = datetime.fromisoformat(job_data['last_work_time'])
            cooldown = timedelta(hours=4)
            if datetime.now() - last_work < cooldown:
                time_left = cooldown - (datetime.now() - last_work)
                hours = int(time_left.total_seconds() // 3600)
                minutes = int(time_left.total_seconds() % 3600 // 60)
                conn.close()
                return (False, 0, f'You can work again in {hours}h {minutes}m')
        base_earnings = 50
        level_bonus = job_data['job_level'] * 10
        earnings = base_earnings + level_bonus + random.randint((-10), 20)
        earnings = apply_booster_multiplier(user_id, earnings)
        add_coins(user_id, earnings, 'work', f"Work as {job_data['current_job']} (Level {job_data['job_level']})")
        new_exp = job_data['job_experience'] + 10
        new_level = job_data['job_level']
        new_job = job_data['current_job']
        exp_needed = new_level * 100
        if new_exp >= exp_needed:
            new_level += 1
            new_exp = 0
            jobs = ['Beginner', 'Worker', 'Professional', 'Expert', 'Master', 'Legend']
            job_index = min(new_level // 5, len(jobs) - 1)
            new_job = jobs[job_index]
        cur.execute('UPDATE user_jobs \n                   SET last_work_time = ?, job_experience = ?, job_level = ?, \n                       current_job = ?, total_work_count = total_work_count + 1\n                   WHERE user_id = ?', (datetime.now().isoformat(), new_exp, new_level, new_job, user_id))
        conn.commit()
        conn.close()
        level_up_msg = f'\n🎉 Level up! Now Level {new_level} {new_job}!' if new_level > job_data['job_level'] else ''
        return (True, earnings, f'You earned {earnings:,} coins!{level_up_msg}')
    init_db()
    vps_data = get_vps_data()
    admin_data = {'admins': get_admins()}
    CPU_THRESHOLD = int(get_setting('cpu_threshold', 90))
    RAM_THRESHOLD = int(get_setting('ram_threshold', 90))
    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True
    bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)
    resource_monitor_active = True
    def truncate_text(text, max_length=1024):
        if not text:
            return text
        else:
            if len(text) <= max_length:
                return text
            else:
                return text[:max_length - 3] + '...'
    class EmbedColors:
        """Premium color palette for modern UI"""
        PRIMARY = 5793266
        SUCCESS = 5763719
        ERROR = 15548997
        WARNING = 16705372
        INFO = 5793266
        PREMIUM = 15418782
        GOLD = 15844367
        PURPLE = 10181046
        DARK = 2829617
        LIGHT = 10070709
    class EmbedIcons:
        """Modern icon system for consistent branding"""
        SUCCESS = '✓'
        ERROR = '✕'
        WARNING = '⚠'
        INFO = 'ℹ'
        LOADING = '⟳'
        PREMIUM = '★'
        ARROW = '→'
        BULLET = '•'
        DIVIDER = '─'
    def create_embed(title, description='', color=EmbedColors.PRIMARY, show_branding=True):
        """\n    Create a premium-styled Discord embed with modern design principles\n    \n    Args:\n        title: Main title (clean, no emoji prefix)\n        description: Main content\n        color: Hex color code\n        show_branding: Whether to show footer branding\n    """
        clean_title = truncate_text(title, 256)
        embed = discord.Embed(title=clean_title, description=truncate_text(description, 4096) if description else None, color=color, timestamp=datetime.now(timezone.utc))
        if show_branding:
            embed.set_footer(text=f'{BOT_NAME} v{BOT_VERSION} {EmbedIcons.BULLET} Powered by {BOT_DEVELOPER}', icon_url='https://i.imgur.com/dpatuSj.png')
        return embed
    def add_field(embed, name, value, inline=False):
        """\n    Add a field with clean formatting\n    \n    Args:\n        embed: Discord embed object\n        name: Field name (clean, minimal icons)\n        value: Field value\n        inline: Whether to display inline\n    """
        clean_name = truncate_text(name, 256)
        clean_value = truncate_text(value if value else 'N/A', 1024)
        embed.add_field(name=clean_name, value=clean_value, inline=inline)
        return embed
    def create_success_embed(title, description='', show_icon=True):
        """\n    Success state embed - Clean green design\n    \n    Usage: Successful operations, confirmations\n    """
        icon = f'{EmbedIcons.SUCCESS} ' if show_icon else ''
        return create_embed(f'{icon}{title}', description, color=EmbedColors.SUCCESS)
    def create_error_embed(title, description='', show_icon=True):
        """\n    Error state embed - Clean red design\n    \n    Usage: Errors, failures, access denied\n    """
        icon = f'{EmbedIcons.ERROR} ' if show_icon else ''
        return create_embed(f'{icon}{title}', description, color=EmbedColors.ERROR)
    def create_info_embed(title, description='', show_icon=True):
        """\n    Information embed - Clean blue design\n    \n    Usage: General information, help text\n    """
        icon = f'{EmbedIcons.INFO} ' if show_icon else ''
        return create_embed(f'{icon}{title}', description, color=EmbedColors.INFO)
    def create_warning_embed(title, description='', show_icon=True):
        """\n    Warning state embed - Clean yellow design\n    \n    Usage: Warnings, cautions, confirmations needed\n    """
        icon = f'{EmbedIcons.WARNING} ' if show_icon else ''
        return create_embed(f'{icon}{title}', description, color=EmbedColors.WARNING)
    def create_premium_embed(title, description=''):
        """\n    Premium feature embed - Special pink/purple design\n    \n    Usage: Premium features, special announcements\n    """
        return create_embed(f'{EmbedIcons.PREMIUM} {title}', description, color=EmbedColors.PREMIUM)
    def create_loading_embed(title, description='Processing your request...'):
        """\n    Loading state embed - Indicates ongoing process\n    \n    Usage: Long-running operations\n    """
        return create_embed(f'{EmbedIcons.LOADING} {title}', description, color=EmbedColors.INFO)
    def create_card_embed(title, description='', color=EmbedColors.DARK):
        """\n    Card-style embed for displaying structured data\n    \n    Usage: VPS info, user profiles, statistics\n    """
        embed = create_embed(title, description, color)
        return embed
    def format_progress_bar(current, maximum, length=10, filled='█', empty='░'):
        """\n    Create a modern progress bar\n    \n    Args:\n        current: Current value\n        maximum: Maximum value\n        length: Bar length in characters\n        filled: Character for filled portion\n        empty: Character for empty portion\n    \n    Returns:\n        Formatted progress bar string with percentage\n    """
        if maximum == 0:
            percentage = 0
        else:
            percentage = min(100, int(current / maximum * 100))
        filled_length = int(percentage / 100 * length)
        bar = filled * filled_length + empty * (length - filled_length)
        return f'{bar} {percentage}%'
    def format_status_badge(status, online_text='Online', offline_text='Offline'):
        """\n    Create a status badge with color indicator\n    \n    Args:\n        status: Boolean or string status\n        online_text: Text for online/active state\n        offline_text: Text for offline/inactive state\n    \n    Returns:\n        Formatted status string with indicator\n    """
        if isinstance(status, bool):
            is_online = status
        else:
            is_online = status.lower() in ['running', 'online', 'active', 'started']
        indicator = '🟢' if is_online else '🔴'
        text = online_text if is_online else offline_text
        return f'{indicator} **{text}**'
    def format_metric(label, value, unit='', icon=''):
        """\n    Format a metric with consistent styling\n    \n    Args:\n        label: Metric label\n        value: Metric value\n        unit: Unit of measurement\n        icon: Optional icon\n    \n    Returns:\n        Formatted metric string\n    """
        icon_str = f'{icon} ' if icon else ''
        unit_str = f' {unit}' if unit else ''
        return f'{icon_str}**{label}:** {value}{unit_str}'
    def create_divider(char='─', length=30):
        """Create a visual divider for embed sections"""
        return char * length
    def format_list_item(text, bullet=EmbedIcons.BULLET):
        """Format a list item with consistent bullet style"""
        return f'{bullet} {text}'
    def create_section_header(text):
        """Create a section header with subtle styling"""
        return f'**{text}**'
    def is_admin():
        async def predicate(ctx):
            user_id = str(ctx.author.id)
            if user_id == str(MAIN_ADMIN_ID) or user_id in admin_data.get('admins', []):
                return True
            else:
                raise commands.CheckFailure('You need admin permissions to use this command. Contact support.')
        return commands.check(predicate)
    def is_main_admin():
        async def predicate(ctx):
            if str(ctx.author.id) == str(MAIN_ADMIN_ID):
                return True
            else:
                raise commands.CheckFailure('Only the main admin can use this command.')
        return commands.check(predicate)
    async def execute_lxc(container_name: str, command: str, timeout=120, node_id: Optional[int]=None):
        # irreducible cflow, using cdg fallback
        if node_id is None:
            node_id = find_node_id_for_container(container_name)
        node = get_node(node_id)
        if not node:
            raise Exception(f'Node {node_id} not found')
        full_command = f'lxc {command}'
        if node['is_local']:
            cmd = shlex.split(full_command)
            proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                raise asyncio.TimeoutError(f'Command timed out after {timeout} seconds')
            if proc.returncode!= 0:
                error = stderr.decode().strip() if stderr else 'Command failed with no error output'
                raise Exception(f'Local LXC command failed: {error}\nCommand: {full_command}')
            return stdout.decode().strip() if stdout else True
            url = f"{node['url']}/api/execute"
            data = {'command': full_command}
            params = {'api_key': node['api_key']}
            try:
                response = requests.post(url, json=data, params=params, timeout=timeout)
                try:
                    error_detail = response.json()
                    if 'detail' in error_detail:
                        error_msg = error_detail['detail']
                    else:
                        if 'error' in error_detail:
                            error_msg = error_detail['error']
                        else:
                            error_msg = response.text
                except:
                    error_msg = response.text
                response.raise_for_status()
                res = response.json()
                if res.get('returncode', 1)!= 0:
                    stderr = res.get('stderr', 'Command failed')
                    raise Exception(f"Remote LXC command failed on {node['name']}: {stderr}\nCommand: {full_command}")
                else:
                    return res.get('stdout', True)
            except requests.exceptions.RequestException as e:
                logger.error(f"Remote LXC error on node {node['name']} ({url}): {str(e)}")
                if hasattr(e.response, 'status_code'):
                    raise Exception(f"Remote execution failed on {node['name']}: HTTP {e.response.status_code} - {str(e)}")
                else:
                    raise Exception(f"Remote execution failed on {node['name']}: {str(e)}")
                    except asyncio.TimeoutError as te:
                            logger.error(f'LXC command timed out: {full_command} - {str(te)}')
                            raise
                        except Exception as e:
                                logger.error(f'LXC Error: {full_command} - {str(e)}')
                                raise
    async def apply_lxc_config(container_name: str, node_id: int):
        # irreducible cflow, using cdg fallback
        try:
            await execute_lxc(container_name, f'config set {container_name} security.nesting true', node_id=node_id)
            await execute_lxc(container_name, f'config set {container_name} security.privileged true', node_id=node_id)
            await execute_lxc(container_name, f'config set {container_name} security.syscalls.intercept.mknod true', node_id=node_id)
            await execute_lxc(container_name, f'config set {container_name} security.syscalls.intercept.setxattr true', node_id=node_id)
            await execute_lxc(container_name, f'config set {container_name} linux.kernel_modules overlay,loop,nf_nat,ip_tables,ip6_tables,netlink_diag,br_netfilter', node_id=node_id)
            try:
                await execute_lxc(container_name, f'config device add {container_name} fuse unix-char path=/dev/fuse', node_id=node_id)
            except:
                pass
            raw_lxc_config = 'lxc.apparmor.profile = unconfined\nlxc.apparmor.allow_nesting = 1\nlxc.apparmor.allow_incomplete = 1\n\nlxc.cap.drop =\nlxc.cgroup.devices.allow = a\nlxc.cgroup2.devices.allow = a\n\nlxc.mount.auto = proc:rw sys:rw cgroup:rw shmounts:rw\n\nlxc.mount.entry = /dev/fuse dev/fuse none bind,create=file 0 0\n'
            await execute_lxc(container_name, f'config set {container_name} raw.lxc \'{raw_lxc_config}\'', node_id=node_id)
            logger.info(f'LXC permissions applied to {container_name} on node {node_id}')
        except Exception as e:
            logger.error(f'Failed to apply LXC config to {container_name}: {e}')
    async def apply_internal_permissions(container_name: str, node_id: int):
        # irreducible cflow, using cdg fallback
        try:
            await asyncio.sleep(5)
            commands = ['mkdir -p /etc/sysctl.d/', 'echo \'net.ipv4.ip_unprivileged_port_start=0\' > /etc/sysctl.d/99-custom.conf', 'echo \'net.ipv4.ping_group_range=0 2147483647\' >> /etc/sysctl.d/99-custom.conf', 'echo \'fs.inotify.max_user_watches=524288\' >> /etc/sysctl.d/99-custom.conf', 'echo \'kernel.unprivileged_userns_clone=1\' >> /etc/sysctl.d/99-custom.conf', 'sysctl -p /etc/sysctl.d/99-custom.conf || true']
            for cmd in commands:
                try:
                    await execute_lxc(container_name, f'exec {container_name} -- bash -c \"{cmd}\"', node_id=node_id)
                except Exception as cmd_error:
                    logger.warning(f'Command failed in {container_name}: {cmd} - {cmd_error}')
                else:
                    pass
            logger.info(f'Internal permissions applied to {container_name}')
        except Exception as e:
            logger.error(f'Failed to apply internal permissions to {container_name}: {e}')
    async def get_or_create_vps_role(guild):
        global VPS_USER_ROLE_ID
        me = guild.me
        if not me or not me.guild_permissions.manage_roles:
            return None
        else:
            role_name = f'{BOT_NAME} VPS User'
            if VPS_USER_ROLE_ID:
                role = guild.get_role(VPS_USER_ROLE_ID)
                if role and role < me.top_role:
                    return role
                else:
                    VPS_USER_ROLE_ID = None
            role = discord.utils.get(guild.roles, name=role_name)
            if role:
                if role >= me.top_role:
                    try:
                        await role.delete(reason='Role above bot, recreating')
                    except discord.Forbidden:
                        return
                    role = None
                else:
                    VPS_USER_ROLE_ID = role.id
                    return role
            try:
                role = await guild.create_role(name=role_name, color=discord.Color.dark_purple(), permissions=discord.Permissions.none(), reason=f'{BOT_NAME} VPS User role')
                await role.edit(position=me.top_role.position - 1)
                VPS_USER_ROLE_ID = role.id
                logger.info(f'Created VPS role: {role.id}')
                return role
            except Exception as e:
                logger.error(f'Failed to create VPS role: {e}')
    def get_host_cpu_usage():
        # irreducible cflow, using cdg fallback
        """Get host CPU usage - cross-platform"""
        import psutil
        return psutil.cpu_percent(interval=1)
            except ImportError:
                    pass
                    if shutil.which('mpstat'):
                        pass
                    pass
                        result = subprocess.run(['mpstat', '1', '1'], capture_output=True, text=True)
                        output = result.stdout
                        for line in output.split('\n'):
                            if 'all' in line and '%' in line:
                                else:
                                    parts = line.split()
                                    idle = float(parts[(-1)])
                                    return 100.0 - idle
                            return 0.0
                        if shutil.which('top'):
                            result = subprocess.run(['top', '-bn1'], capture_output=True, text=True)
                            output = result.stdout
                            for line in output.split('\n'):
                                if '%Cpu(s):' in line:
                                    pass
                                else:
                                    parts = line.split()
                                    us = float(parts[1])
                                    sy = float(parts[3])
                                    ni = float(parts[5])
                                    id_ = float(parts[7])
                                    wa = float(parts[9])
                                    hi = float(parts[11])
                                    si = float(parts[13])
                                    st = float(parts[15])
                                    usage = us + sy + ni + wa + hi + si + st
                                    return usage
                            return 0.0
                        except Exception as e:
                                logger.error(f'Error getting CPU usage: {e}')
                                    return 0.0
                                    pass
                                        pass
    def get_host_ram_usage():
        # irreducible cflow, using cdg fallback
        """Get host RAM usage - cross-platform"""
        import psutil
        return psutil.virtual_memory().percent
            except ImportError:
                    pass
                    if shutil.which('free'):
                        result = subprocess.run(['free', '-m'], capture_output=True, text=True)
                        lines = result.stdout.splitlines()
                        if len(lines) > 1:
                            mem = lines[1].split()
                            total = int(mem[1])
                            used = int(mem[2])
                            return used / total * 100 if total > 0 else 0.0
                    pass
                        return 0.0
                        except Exception as e:
                                logger.error(f'Error getting RAM usage: {e}')
                                    return 0.0
    async def get_host_stats(node_id: int) -> Dict:
        # irreducible cflow, using cdg fallback
        node = get_node(node_id)
        if node['is_local']:
            return {'cpu': get_host_cpu_usage(), 'ram': get_host_ram_usage()}
        else:
            url = f"{node['url']}/api/get_host_stats"
            params = {'api_key': node['api_key']}
            response = requests.get(url, params=params)
            response.raise_for_status()
            return response.json()
                except Exception as e:
                        logger.error(f"Failed to get host stats from node {node['name']}: {e}")
                        return {'cpu': 0.0, 'ram': 0.0}
    def resource_monitor():
        while resource_monitor_active:
            try:
                nodes = get_nodes()
                for node in nodes:
                    stats = asyncio.run(get_host_stats(node['id']))
                    cpu = stats['cpu']
                    ram = stats['ram']
                    logger.info(f"Node {node['name']}: CPU {cpu:.1f}%, RAM {ram:.1f}%")
                    if cpu > CPU_THRESHOLD or ram > RAM_THRESHOLD:
                        logger.warning(f"Node {node['name']} exceeded thresholds (CPU: {CPU_THRESHOLD}%, RAM: {RAM_THRESHOLD}%). Manual intervention required.")
                time.sleep(60)
            except Exception as e:
                logger.error(f'Error in resource monitor: {e}')
                time.sleep(60)
    monitor_thread = threading.Thread(target=resource_monitor, daemon=True)
    monitor_thread.start()
    async def get_container_stats(container_name: str, node_id: Optional[int]=None) -> Dict:
        # irreducible cflow, using cdg fallback
        if node_id is None:
            node_id = find_node_id_for_container(container_name)
        node = get_node(node_id)
        if node['is_local']:
            status = await get_container_status_local(container_name)
            cpu = await get_container_cpu_pct_local(container_name)
            ram = await get_container_ram_local(container_name)
            disk = await get_container_disk_local(container_name)
            uptime = await get_container_uptime_local(container_name)
            return {'status': status, 'cpu': cpu, 'ram': ram, 'disk': disk, 'uptime': uptime}
        else:
            url = f"{node['url']}/api/get_container_stats"
            data = {'container': container_name}
            params = {'api_key': node['api_key']}
            response = requests.post(url, json=data, params=params)
            response.raise_for_status()
            return response.json()
                except Exception as e:
                        logger.error(f"Failed to get container stats from node {node['name']}: {e}")
                        return {'status': 'unknown', 'cpu': 0.0, 'ram': {'used': 0, 'total': 0, 'pct': 0.0}, 'disk': 'Unknown', 'uptime': 'Unknown'}
    async def get_container_status_local(container_name: str):
        # irreducible cflow, using cdg fallback
        proc = await asyncio.create_subprocess_exec('lxc', 'info', container_name, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, _ = await proc.communicate()
        output = stdout.decode()
        for line in output.splitlines():
                if line.startswith('Status: '):
                    return line.split(': ', 1)[1].strip().lower()
                    return 'unknown'
                    except Exception:
                            return 'unknown'
    async def get_container_cpu_pct_local(container_name: str):
        # irreducible cflow, using cdg fallback
        proc = await asyncio.create_subprocess_exec('lxc', 'exec', container_name, '--', 'top', '-bn1', stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await proc.communicate()
        output = stdout.decode()
        for line in output.splitlines():
                if '%Cpu(s):' in line or 'Cpu(s):' in line:
                    parts = line.split()
                    cpu_total = 0.0
                    for i, part in enumerate(parts):
                        if part in ['us,', 'sy,', 'ni,', 'wa,', 'hi,', 'si,', 'st,', 'st'] and i > 0:
                                try:
                                    value = float(parts[i - 1].replace('%', '').replace(',', ''))
                                    if part not in ['id,', 'id']:
                                        cpu_total += value
                                except (ValueError, IndexError):
                                    pass
                                else:
                                    pass
                    return cpu_total if cpu_total > 0 else 0.0
                proc = await asyncio.create_subprocess_exec('lxc', 'exec', container_name, '--', 'cat', '/proc/loadavg', stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                stdout, _ = await proc.communicate()
                output = stdout.decode().strip()
                if output:
                    load = float(output.split()[0])
                    return min(load * 25, 100.0)
                    return 0.0
                        except Exception as e:
                                logger.error(f'Error parsing CPU line for {container_name}: {e}')
                except Exception as e:
                        logger.error(f'Error getting CPU for {container_name}: {e}')
                            return 0.0
    async def get_container_ram_local(container_name: str):
        # irreducible cflow, using cdg fallback
        proc = await asyncio.create_subprocess_exec('lxc', 'exec', container_name, '--', 'free', '-m', stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, _ = await proc.communicate()
        lines = stdout.decode().splitlines()
        if len(lines) > 1:
            parts = lines[1].split()
            total = int(parts[1])
            used = int(parts[2])
            pct = used / total * 100 if total > 0 else 0.0
            return {'used': used, 'total': total, 'pct': pct}
            return {'used': 0, 'total': 0, 'pct': 0.0}
                except Exception as e:
                        logger.error(f'Error getting RAM for {container_name}: {e}')
                        return {'used': 0, 'total': 0, 'pct': 0.0}
    async def get_container_disk_local(container_name: str):
        # irreducible cflow, using cdg fallback
        proc = await asyncio.create_subprocess_exec('lxc', 'exec', container_name, '--', 'df', '-h', '/', stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, _ = await proc.communicate()
        lines = stdout.decode().splitlines()
        for line in lines:
                if '/dev/' in line and ' /' in line:
                        parts = line.split()
                        if len(parts) >= 5:
                            used = parts[2]
                            size = parts[1]
                            perc = parts[4]
                            return f'{used}/{size} ({perc})'
                    return 'Unknown'
                    except Exception:
                            return 'Unknown'
                            pass
    async def get_container_uptime_local(container_name: str):
        # irreducible cflow, using cdg fallback
        proc = await asyncio.create_subprocess_exec('lxc', 'exec', container_name, '--', 'uptime', stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, _ = await proc.communicate()
        return stdout.decode().strip() if stdout else 'Unknown'
                except Exception:
                        return 'Unknown'
    async def get_container_status(container_name: str, node_id: Optional[int]=None):
        stats = await get_container_stats(container_name, node_id)
        return stats['status']
    async def get_container_cpu(container_name: str, node_id: Optional[int]=None):
        stats = await get_container_stats(container_name, node_id)
        return f"{stats['cpu']:.1f}%"
    async def get_container_cpu_pct(container_name: str, node_id: Optional[int]=None):
        stats = await get_container_stats(container_name, node_id)
        return stats['cpu']
    async def get_container_memory(container_name: str, node_id: Optional[int]=None):
        stats = await get_container_stats(container_name, node_id)
        ram = stats['ram']
        return f"{ram['used']}/{ram['total']} MB ({ram['pct']:.1f}%)"
    async def get_container_ram_pct(container_name: str, node_id: Optional[int]=None):
        stats = await get_container_stats(container_name, node_id)
        return stats['ram']['pct']
    async def get_container_disk(container_name: str, node_id: Optional[int]=None):
        stats = await get_container_stats(container_name, node_id)
        return stats['disk']
    async def get_container_uptime(container_name: str, node_id: Optional[int]=None):
        stats = await get_container_stats(container_name, node_id)
        return stats['uptime']
    def get_uptime():
        # irreducible cflow, using cdg fallback
        """Get system uptime - cross-platform"""
        try:
            import psutil
            boot_time = psutil.boot_time()
            uptime_seconds = time.time() - boot_time
            days = int(uptime_seconds // 86400)
            hours = int(uptime_seconds % 86400 // 3600)
            minutes = int(uptime_seconds % 3600 // 60)
            if days > 0:
                return f'{days}d {hours}h {minutes}m'
            else:
                if hours > 0:
                    return f'{hours}h {minutes}m'
                else:
                    return f'{minutes}m'
        except ImportError:
            pass
        if shutil.which('uptime'):
            result = subprocess.run(['uptime'], capture_output=True, text=True)
            return result.stdout.strip()
            return 'Unknown'
                except Exception as e:
                        logger.error(f'Error getting uptime: {e}')
                            return 'Unknown'
                            pass
                                pass
    def get_default_storage_pool():
        # irreducible cflow, using cdg fallback
        result = subprocess.run(['lxc', 'storage', 'list', '--format', 'csv'], capture_output=True, text=True)
        lines = result.stdout.strip().split('\n')
        if lines and lines[0]:
            return lines[0].split(',')[0]
            return 'default'
                    return 'default'
                    pass
    DEFAULT_STORAGE_POOL = os.getenv('DEFAULT_STORAGE_POOL', get_default_storage_pool())
    @bot.event
    async def on_ready():
        logger.info(f'{bot.user} has connected to Discord!')
        await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=f'{BOT_NAME} VPS Manager'))
        logger.info(f'{BOT_NAME} Bot is ready!')
        bot.loop.create_task(expiration_checker_loop())
    user_message_cooldown = {}
    @bot.event
    async def on_message(message):
        if message.author.bot:
            await bot.process_commands(message)
        else:
            await bot.process_commands(message)
    @bot.event
    async def on_member_join(member):
        """Track invites when members join - WITH COMPREHENSIVE ANTI-EXPLOIT PROTECTION"""
        if member.bot:
            return
        else:
            try:
                invites_before = bot.cached_invites.get(member.guild.id, {})
                invites_after = await member.guild.invites()
                for invite in invites_after:
                    if invite.code in invites_before and invite.uses > invites_before[invite.code]:
                            inviter_id = str(invite.inviter.id)
                            invited_id = str(member.id)
                            if is_user_restricted(inviter_id):
                                log_security_event(inviter_id, 'restricted_invite_attempt', f'Restricted user attempted to earn from invite: {member.name}', 'medium')
                                break
                            else:
                                allowed, remaining = check_rate_limit(inviter_id, 'invite', 10, 60)
                                if not allowed:
                                    log_security_event(inviter_id, 'invite_rate_limit', f'Invite rate limit exceeded. {remaining}s remaining', 'medium')
                                    update_trust_score(inviter_id, (-5), 'Invite spam detected')
                                    await notify_admins_security('Invite Spam Detected', f'<@{inviter_id}> exceeded invite rate limit (10/hour)\nInvited: {member.mention}', inviter_id)
                                    break
                                else:
                                    conn = get_db()
                                    cur = conn.cursor()
                                    cur.execute('SELECT * FROM invites \n                                   WHERE inviter_id = ? AND invited_id = ?', (inviter_id, invited_id))
                                    existing_invite = cur.fetchone()
                                    if existing_invite:
                                        logger.info(f'Rejoin detected: {member.name} was already invited by {inviter_id}')
                                        log_security_event(inviter_id, 'rejoin_attempt', f'User {member.name} rejoined - coins not awarded', 'low')
                                        conn.close()
                                        break
                                    else:
                                        cur.execute('SELECT * FROM invites \n                                   WHERE invited_id = ? AND joined_at > datetime(\'now\', \'-1 hour\')', (invited_id,))
                                        recent_join = cur.fetchone()
                                        if recent_join:
                                            logger.warning(f'Rapid rejoin detected: {member.name}')
                                            log_security_event(inviter_id, 'rapid_rejoin', f'User {member.name} joined within 1 hour of previous join', 'high')
                                            update_trust_score(inviter_id, (-10), 'Rapid rejoin spam')
                                            await notify_admins_security('Rapid Rejoin Detected', f'<@{inviter_id}> invited {member.mention} who joined within 1 hour', inviter_id)
                                            conn.close()
                                            break
                                        else:
                                            if inviter_id == invited_id:
                                                logger.warning(f'Self-invite attempt: {member.name}')
                                                log_security_event(inviter_id, 'self_invite', 'Attempted to invite themselves', 'high')
                                                update_trust_score(inviter_id, (-20), 'Self-invite attempt')
                                                await notify_admins_security('Self-Invite Attempt', f'<@{inviter_id}> attempted to invite themselves', inviter_id)
                                                conn.close()
                                                break
                                            else:
                                                coins_per_invite = int(get_setting('coins_per_invite', 50))
                                                def award_invite_coins():
                                                    return add_coins(inviter_id, coins_per_invite, 'invite', f'Invited {member.name}')
                                                new_balance = await run_in_executor(award_invite_coins)
                                                cur.execute('UPDATE user_coins SET invite_count = invite_count + 1 WHERE user_id = ?', (inviter_id,))
                                                cur.execute('INSERT INTO invites (inviter_id, invited_id, joined_at, coins_earned)\n                                   VALUES (?, ?, ?, ?)', (inviter_id, invited_id, datetime.now().isoformat(), coins_per_invite))
                                                conn.commit()
                                                conn.close()
                                                try:
                                                    inviter = await bot.fetch_user(int(inviter_id))
                                                    embed = create_success_embed('🎉 Invite Reward!', f'You earned **{coins_per_invite} coins** for inviting {member.mention}!\nNew balance: **{new_balance:,} coins**')
                                                    await inviter.send(embed=embed)
                                                except:
                                                    pass
                                                logger.info(f'Invite reward: {inviter_id} earned {coins_per_invite} coins for inviting {member.name}')
                                                break
                bot.cached_invites[member.guild.id] = {inv.code: inv.uses for inv in invites_after}
            except Exception as e:
                logger.error(f'Error tracking invite: {e}')
                return
    @bot.event
    async def on_voice_state_update(member, before, after):
        """Track voice activity for coin rewards"""
        user_id = str(member.id)
        if before.channel is None and after.channel is not None:
            conn = get_db()
            cur = conn.cursor()
            cur.execute('INSERT INTO voice_sessions (user_id, started_at)\n                       VALUES (?, ?)', (user_id, datetime.now().isoformat()))
            conn.commit()
            conn.close()
            return
        else:
            if before.channel is None or after.channel is None:
                    conn = get_db()
                    cur = conn.cursor()
                    cur.execute('SELECT id, started_at FROM voice_sessions \n                       WHERE user_id = ? AND ended_at IS NULL \n                       ORDER BY started_at DESC LIMIT 1', (user_id,))
                    row = cur.fetchone()
                    if row:
                        session_id, started_at = row
                        started = datetime.fromisoformat(started_at)
                        duration = (datetime.now() - started).total_seconds() / 60
                        min_duration = int(get_setting('voice_min_duration_minutes', 5))
                        coins_per_minute = int(get_setting('coins_per_voice_minute', 2))
                        if duration >= min_duration:
                            coins_earned = int(duration * coins_per_minute)
                            new_balance = add_coins(user_id, coins_earned, 'voice', f'Voice activity: {int(duration)} minutes')
                            cur.execute('UPDATE voice_sessions \n                               SET ended_at = ?, duration_minutes = ?, coins_earned = ?\n                               WHERE id = ?', (datetime.now().isoformat(), int(duration), coins_earned, session_id))
                            cur.execute('UPDATE user_coins SET voice_minutes = voice_minutes + ? WHERE user_id = ?', (int(duration), user_id))
                            conn.commit()
                            try:
                                embed = create_success_embed('🎤 Voice Reward!', f'You earned **{coins_earned} coins** for {int(duration)} minutes in voice!\nNew balance: **{new_balance} coins**')
                                await member.send(embed=embed)
                            except:
                                pass
                            else:
                                pass
                        else:
                            cur.execute('UPDATE voice_sessions \n                               SET ended_at = ?, duration_minutes = ?\n                               WHERE id = ?', (datetime.now().isoformat(), int(duration), session_id))
                            conn.commit()
                    conn.close()
    bot.cached_invites = {}
    @bot.event
    async def on_guild_join(guild):
        # irreducible cflow, using cdg fallback
        """Cache invites when bot joins a guild"""
        try:
            invites = await guild.invites()
            bot.cached_invites[guild.id] = {inv.code: inv.uses for inv in invites}
        except:
            return None
    async def expiration_checker_loop():
        # irreducible cflow, using cdg fallback
        """Background task to check for expired VPS and send warnings"""
        await bot.wait_until_ready()
        warned_24h = set()
        warned_12h = set()
        warned_1h = set()
        while not bot.is_closed():
            suspended_count = check_and_suspend_expired_vps()
            if suspended_count > 0:
                logger.info(f'Auto-suspended {suspended_count} expired VPS')
            conn = get_db()
            cur = conn.cursor()
            cur.execute('SELECT id, user_id, container_name, expires_at, whitelisted\n                           FROM vps \n                           WHERE expires_at IS NOT NULL \n                           AND suspended = 0\n                           AND whitelisted = 0')
            all_vps = cur.fetchall()
            conn.close()
            for vps in all_vps:
                    vps_id, user_id, container_name, expires_at_str, whitelisted = vps
                    if not expires_at_str or whitelisted:
                        continue
                    else:
                        expires_at = datetime.fromisoformat(expires_at_str)
                        hours_left = (expires_at - datetime.now()).total_seconds() / 3600
                        if hours_left <= 0:
                            continue
                        user = await bot.fetch_user(int(user_id))
                        renewal_cost_1day = int(get_setting('coins_vps_renewal_1day', 50))
                        renewal_cost_7days = int(get_setting('coins_vps_renewal_7days', 300))
                        if 23 <= hours_left <= 25 and vps_id not in warned_24h:
                                embed = create_warning_embed('⚠️ VPS Expiring in 24 Hours!', f"Your VPS `{container_name}` will expire in **24 hours**!\n\n**Expires:** {expires_at.strftime('%Y-%m-%d %H:%M:%S')}\n**VPS ID:** {vps_id}\n\n**Renewal Options:**\n• 1 Day: {renewal_cost_1day} coins\n• 7 Days: {renewal_cost_7days} coins\n\n**Renew Now:** `{PREFIX}renew {vps_id} <days>`\n**Check Balance:** `{PREFIX}balance`")
                                embed.set_footer(text=f'{BOT_NAME} • VPS Expiration Warning')
                                await user.send(embed=embed)
                                warned_24h.add(vps_id)
                                logger.info(f'Sent 24h warning to user {user_id} for VPS {container_name}')
                                if 11 <= hours_left <= 13 and vps_id not in warned_12h:
                                        embed = create_warning_embed('🚨 VPS Expiring in 12 Hours!', f"**URGENT:** Your VPS `{container_name}` will expire in **12 hours**!\n\n**Expires:** {expires_at.strftime('%Y-%m-%d %H:%M:%S')}\n**VPS ID:** {vps_id}\n\n**Renewal Options:**\n• 1 Day: {renewal_cost_1day} coins\n• 7 Days: {renewal_cost_7days} coins\n\n**Renew Now:** `{PREFIX}renew {vps_id} <days>`\n**Earn Coins:** `{PREFIX}daily`, `{PREFIX}work`")
                                        embed.set_footer(text=f'{BOT_NAME} • URGENT Expiration Warning')
                                        await user.send(embed=embed)
                                        warned_12h.add(vps_id)
                                        logger.info(f'Sent 12h warning to user {user_id} for VPS {container_name}')
                                        if 0.5 <= hours_left <= 1.5 and vps_id not in warned_1h:
                                                    embed = create_error_embed('⏰ VPS EXPIRING IN 1 HOUR!', f"**CRITICAL:** Your VPS `{container_name}` will expire in **1 hour**!\n\n**Expires:** {expires_at.strftime('%Y-%m-%d %H:%M:%S')}\n**VPS ID:** {vps_id}\n\n**After expiration, your VPS will be SUSPENDED!**\n\n**Quick Renewal:**\n• 1 Day: {renewal_cost_1day} coins → `{PREFIX}renew {vps_id} 1`\n• 7 Days: {renewal_cost_7days} coins → `{PREFIX}renew {vps_id} 7`\n\n**Check Balance:** `{PREFIX}balance`")
                                                    embed.set_footer(text=f'{BOT_NAME} • CRITICAL Expiration Warning')
                                                    await user.send(embed=embed)
                                                    warned_1h.add(vps_id)
                                                    logger.info(f'Sent 1h warning to user {user_id} for VPS {container_name}')
                    current_vps_ids = {vps[0] for vps in all_vps}
                    warned_24h = warned_24h & current_vps_ids
                    warned_12h = warned_12h & current_vps_ids
                    warned_1h = warned_1h & current_vps_ids
                                    await asyncio.sleep(600)
                                        except discord.Forbidden:
                                            logger.warning(f'Cannot DM user {user_id} - DMs disabled')
                                                pass
                                            except Exception as e:
                                                    logger.error(f'Failed to send expiration warning to user {user_id}: {e}')
                                                        pass
                    except Exception as e:
                            logger.error(f'Error in expiration checker: {e}')
    @bot.event
    async def on_command_error(ctx, error):
        if isinstance(error, commands.CommandNotFound):
            return
        else:
            if isinstance(error, commands.MissingRequiredArgument):
                await ctx.send(embed=create_error_embed('Missing Argument', 'Please check command usage with `!help`.'))
            else:
                if isinstance(error, commands.BadArgument):
                    await ctx.send(embed=create_error_embed('Invalid Argument', 'Please check your input and try again.'))
                else:
                    if isinstance(error, commands.CheckFailure):
                        error_msg = str(error) if str(error) else 'You need admin permissions for this command. Contact support.'
                        await ctx.send(embed=create_error_embed('Access Denied', error_msg))
                    else:
                        if isinstance(error, discord.NotFound):
                            await ctx.send(embed=create_error_embed('Error', 'The requested resource was not found. Please try again.'))
                        else:
                            logger.error(f'Command error: {error}')
                            await ctx.send(embed=create_error_embed('System Error', 'An unexpected error occurred. Support has been notified.'))
    def check_rate_limit(user_id: str, action_type: str, max_actions: int, window_minutes: int) -> tuple[bool, int]:
        """\n    Check if user has exceeded rate limit for an action\n    Returns: (is_allowed, remaining_seconds)\n    """
        try:
            conn = get_db()
            cur = conn.cursor()
            now = datetime.now()
            cur.execute('SELECT * FROM rate_limits \n                       WHERE user_id = ? AND action_type = ?', (user_id, action_type))
            record = cur.fetchone()
            if not record:
                cur.execute('INSERT INTO rate_limits \n                           (user_id, action_type, action_count, window_start, last_action)\n                           VALUES (?, ?, 1, ?, ?)', (user_id, action_type, now.isoformat(), now.isoformat()))
                conn.commit()
                conn.close()
                return (True, 0)
            else:
                record = dict(record)
                window_start = datetime.fromisoformat(record['window_start'])
                window_elapsed = (now - window_start).total_seconds() / 60
                if window_elapsed >= window_minutes:
                    cur.execute('UPDATE rate_limits \n                           SET action_count = 1, window_start = ?, last_action = ?\n                           WHERE user_id = ? AND action_type = ?', (now.isoformat(), now.isoformat(), user_id, action_type))
                    conn.commit()
                    conn.close()
                    return (True, 0)
                else:
                    if record['action_count'] >= max_actions:
                        remaining_seconds = int(window_minutes * 60 - window_elapsed * 60)
                        conn.close()
                        return (False, remaining_seconds)
                    else:
                        cur.execute('UPDATE rate_limits \n                       SET action_count = action_count + 1, last_action = ?\n                       WHERE user_id = ? AND action_type = ?', (now.isoformat(), user_id, action_type))
                        conn.commit()
                        conn.close()
                        return (True, 0)
        except Exception as e:
            logger.error(f'Rate limit check error: {e}')
            return (True, 0)
    def log_security_event(user_id: str, activity_type: str, description: str, severity: str='low', additional_data: str=None):
        """Log suspicious activity for security monitoring"""
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute('INSERT INTO security_logs \n                       (user_id, activity_type, description, severity, created_at, additional_data)\n                       VALUES (?, ?, ?, ?, ?, ?)', (user_id, activity_type, description, severity, datetime.now().isoformat(), additional_data))
            if severity in ['high', 'critical']:
                cur.execute('UPDATE security_logs SET flagged = 1 \n                           WHERE user_id = ? AND activity_type = ? \n                           ORDER BY created_at DESC LIMIT 1', (user_id, activity_type))
            conn.commit()
            conn.close()
            logger.warning(f'SECURITY [{severity.upper()}]: User {user_id} - {activity_type}: {description}')
        except Exception as e:
            logger.error(f'Failed to log security event: {e}')
    def update_trust_score(user_id: str, change: int, reason: str=None):
        """Update user\'s trust score (0-100)"""
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute('INSERT OR IGNORE INTO user_trust \n                       (user_id, trust_score, warnings, violations)\n                       VALUES (?, 100, 0, 0)', (user_id,))
            cur.execute('UPDATE user_trust \n                       SET trust_score = MAX(0, MIN(100, trust_score + ?))\n                       WHERE user_id = ?', (change, user_id))
            if change < 0:
                cur.execute('UPDATE user_trust \n                           SET violations = violations + 1,\n                               last_violation = ?,\n                               notes = COALESCE(notes || \'\n\', \'\') || ?\n                           WHERE user_id = ?', (datetime.now().isoformat(), f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] {reason or 'Violation'}", user_id))
            cur.execute('SELECT trust_score FROM user_trust WHERE user_id = ?', (user_id,))
            new_score = cur.fetchone()['trust_score']
            if new_score < 20:
                cur.execute('UPDATE user_trust SET restricted = 1 WHERE user_id = ?', (user_id,))
                log_security_event(user_id, 'auto_restriction', f'User auto-restricted due to low trust score ({new_score})', 'high')
            conn.commit()
            conn.close()
            return new_score
        except Exception as e:
            logger.error(f'Failed to update trust score: {e}')
            return 100
    def is_user_restricted(user_id: str) -> bool:
        """Check if user is restricted from earning coins"""
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute('SELECT restricted FROM user_trust WHERE user_id = ?', (user_id,))
            result = cur.fetchone()
            conn.close()
            return result['restricted'] == 1 if result else False
        except Exception as e:
            logger.error(f'Failed to check restriction: {e}')
            return False
    async def notify_admins_security(title: str, description: str, user_id: str=None):
        # irreducible cflow, using cdg fallback
        """Notify admins of security events"""
        try:
            embed = create_error_embed(f'🚨 Security Alert: {title}', description)
            if user_id:
                add_field(embed, 'User ID', f'<@{user_id}> ({user_id})', False)
            add_field(embed, 'Timestamp', datetime.now().strftime('%Y-%m-%d %H:%M:%S'), False)
            try:
                admin = await bot.fetch_user(MAIN_ADMIN_ID)
                await admin.send(embed=embed)
            except:
                pass
            for admin_id in admin_data.get('admins', []):
                try:
                    admin = await bot.fetch_user(int(admin_id))
                    await admin.send(embed=embed)
                except:
                    pass
                else:
                    pass
        except Exception as e:
            logger.error(f'Failed to notify admins: {e}')
            return
    @bot.command(name='ping')
    async def ping(ctx):
        """Check bot latency and connection status"""
        latency = round(bot.latency * 1000)
        if latency < 100:
            quality = 'Excellent'
            color = EmbedColors.SUCCESS
            emoji = '🟢'
        else:
            if latency < 200:
                quality = 'Good'
                color = EmbedColors.INFO
                emoji = '🟡'
            else:
                quality = 'Poor'
                color = EmbedColors.WARNING
                emoji = '🔴'
        embed = create_embed('Connection Status', color=color)
        add_field(embed, 'Latency', f'{emoji} **{latency}ms** ({quality})', True)
        add_field(embed, 'Status', format_status_badge(True, 'Operational'), True)
        add_field(embed, 'Uptime', f'🕐 {get_uptime()}', True)
        await ctx.send(embed=embed)
    @bot.command(name='uptime')
    async def uptime(ctx):
        """Display system uptime information"""
        up = get_uptime()
        embed = create_info_embed('System Uptime', show_icon=False)
        embed.set_thumbnail(url='https://i.imgur.com/dpatuSj.png')
        add_field(embed, '🕐 Host Uptime', f'```{up}```', False)
        add_field(embed, '📊 Status', 'All systems operational', False)
        await ctx.send(embed=embed)
    @bot.command(name='thresholds')
    @is_admin()
    async def thresholds(ctx):
        """View current resource monitoring thresholds"""
        embed = create_card_embed('Resource Thresholds', 'Current monitoring limits for auto-suspension')
        add_field(embed, '🔴 CPU Threshold', f'```{CPU_THRESHOLD}%```', True)
        add_field(embed, '🔵 RAM Threshold', f'```{RAM_THRESHOLD}%```', True)
        add_field(embed, '⚙️ Action', 'Auto-suspend on exceed', True)
        await ctx.send(embed=embed)
    @bot.command(name='set-threshold')
    @is_admin()
    async def set_threshold(ctx, cpu: int, ram: int):
        """Set resource monitoring thresholds"""
        global RAM_THRESHOLD
        global CPU_THRESHOLD
        if cpu < 0 or ram < 0:
            await ctx.send(embed=create_error_embed('Invalid Input', 'Thresholds must be non-negative values.'))
            return
        else:
            CPU_THRESHOLD = cpu
            RAM_THRESHOLD = ram
            set_setting('cpu_threshold', str(cpu))
            set_setting('ram_threshold', str(ram))
            embed = create_success_embed('Thresholds Updated', f'**CPU:** {cpu}%\n**RAM:** {ram}%')
            await ctx.send(embed=embed)
    @bot.command(name='set-status')
    @is_admin()
    async def set_status(ctx, activity_type: str, *, name: str):
        types = {'playing': discord.ActivityType.playing, 'watching': discord.ActivityType.watching, 'listening': discord.ActivityType.listening, 'streaming': discord.ActivityType.streaming}
        if activity_type.lower() not in types:
            await ctx.send(embed=create_error_embed('Invalid Type', 'Valid types: playing, watching, listening, streaming'))
            return
        else:
            await bot.change_presence(activity=discord.Activity(type=types[activity_type.lower()], name=name))
            embed = create_success_embed('Status Updated', f'Set to {activity_type}: {name}')
            await ctx.send(embed=embed)
    @bot.command(name='reload-env')
    @is_admin()
    async def reload_env(ctx):
        # irreducible cflow, using cdg fallback
        """Reload .env configuration without restarting bot"""
        global CPU_THRESHOLD
        global RAM_THRESHOLD
        global PREFIX
        global DEFAULT_STORAGE_POOL
        global BOT_VERSION
        global BOT_NAME
        global BOT_DEVELOPER
        global VPS_USER_ROLE_ID
        global MAIN_ADMIN_ID
        global YOUR_SERVER_IP
        try:
            load_dotenv(override=True)
            BOT_NAME = os.getenv('BOT_NAME', 'UnixNodes')
            PREFIX = os.getenv('PREFIX', '!')
            BOT_VERSION = os.getenv('BOT_VERSION', '7.1-PRO')
            BOT_DEVELOPER = os.getenv('BOT_DEVELOPER', 'Developer')
            MAIN_ADMIN_ID = int(os.getenv('MAIN_ADMIN_ID', '0'))
            YOUR_SERVER_IP = os.getenv('YOUR_SERVER_IP', '127.0.0.1')
            DEFAULT_STORAGE_POOL = os.getenv('DEFAULT_STORAGE_POOL', 'default')
            CPU_THRESHOLD = int(os.getenv('CPU_THRESHOLD', '90'))
            RAM_THRESHOLD = int(os.getenv('RAM_THRESHOLD', '90'))
            VPS_USER_ROLE_ID = int(os.getenv('VPS_USER_ROLE_ID', '0'))
            set_setting('cpu_threshold', str(CPU_THRESHOLD))
            set_setting('ram_threshold', str(RAM_THRESHOLD))
            embed = create_success_embed('✅ Configuration Reloaded', f'Successfully reloaded .env configuration!\n\n**Bot Name:** {BOT_NAME}\n**Prefix:** {PREFIX}\n**Version:** {BOT_VERSION}\n**Server IP:** {YOUR_SERVER_IP}\n**CPU Threshold:** {CPU_THRESHOLD}%\n**RAM Threshold:** {RAM_THRESHOLD}%')
            embed.set_footer(text='Changes applied without restart!')
            await ctx.send(embed=embed)
            logger.info(f'Configuration reloaded by {ctx.author.name}')
        except Exception as e:
            await ctx.send(embed=create_error_embed('Reload Failed', f'Error reloading configuration: {str(e)}'))
            logger.error(f'Failed to reload .env: {e}')
    @bot.command(name='cleanup-shop', aliases=['remove-upgrades', 'clean-shop'])
    @is_admin()
    async def cleanup_shop(ctx):
        # irreducible cflow, using cdg fallback
        """Remove VPS upgrade and extension items from shop database"""
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute('DELETE FROM shop_items WHERE item_type = \'vps_upgrade\'')
            deleted_upgrades = cur.rowcount
            cur.execute('DELETE FROM shop_items WHERE item_type = \'vps_extension\'')
            deleted_extensions = cur.rowcount
            cur.execute('DELETE FROM shop_items WHERE \n                       name LIKE \'%VPS%Upgrade%\' OR \n                       name LIKE \'%RAM Upgrade%\' OR \n                       name LIKE \'%CPU Upgrade%\' OR \n                       name LIKE \'%Disk Upgrade%\' OR\n                       name LIKE \'%VPS Extension%\' OR\n                       name LIKE \'%Extend VPS%\'')
            deleted_by_name = cur.rowcount
            conn.commit()
            conn.close()
            total_deleted = deleted_upgrades + deleted_extensions + deleted_by_name
            if total_deleted > 0:
                embed = create_success_embed('✅ Shop Cleaned Up', f'Removed **{total_deleted}** VPS-related item(s) from the shop.\n\n**VPS Upgrades:** {deleted_upgrades}\n**VPS Extensions:** {deleted_extensions}\n**By Name Pattern:** {deleted_by_name}\n\nVPS upgrades and extensions are no longer available.\nUsers should use `{PREFIX}renew` command instead.')
                logger.info(f'Removed {total_deleted} VPS items from shop (upgrades: {deleted_upgrades}, extensions: {deleted_extensions})')
            else:
                embed = create_info_embed('✅ Shop Already Clean', f'No VPS upgrade or extension items found in the shop.\n\nThe shop is clean! Users can use `{PREFIX}renew` for renewals.')
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=create_error_embed('Cleanup Failed', f'Error: {str(e)}'))
            logger.error(f'Failed to cleanup shop: {e}')
            return
    @bot.command(name='myvps')
    async def my_vps(ctx):
        user_id = str(ctx.author.id)
        vps_list = vps_data.get(user_id, [])
        if not vps_list:
            embed = create_error_embed('❌ No VPS Found', f'You don’t have any **{BOT_NAME} VPS** yet.')
            embed.add_field(name='🚀 Quick Actions', value=f'• `{PREFIX}manage` – Manage VPS\n• Contact an admin to request a VPS', inline=False)
            await ctx.send(embed=embed)
            return
        else:
            embed = create_info_embed(title='🖥️ My VPS Dashboard', description='Your personal VPS overview')
            total_vps = len(vps_list)
            running = suspended = whitelisted = 0
            vps_cards = []
            for i, vps in enumerate(vps_list, start=1):
                node = get_node(vps.get('node_id'))
                node_name = node['name'] if node else 'Unknown'
                config = vps.get('config', 'Custom')
                ram = vps.get('ram', '0GB')
                cpu = vps.get('cpu', '0')
                storage = vps.get('storage', '0GB')
                if vps.get('suspended'):
                    status = '⛔ SUSPENDED'
                    suspended += 1
                else:
                    if vps.get('status') == 'running':
                        status = '🟢 RUNNING'
                        running += 1
                    else:
                        status = '🔴 STOPPED'
                if vps.get('whitelisted'):
                    whitelisted += 1
                expiry_info = format_expiry_time(vps.get('expires_at'))
                vps_cards.append(f"**{i}.** `{vps['container_name']}`\n{status} • `{config}`\n⚙️ `{ram}` RAM • `{cpu}` CPU • `{storage}` Disk\n📍 Node: `{node_name}`\n⏰ Expires: {expiry_info['text']}")
            embed.add_field(name='📊 Summary', value=f'🖥️ `{total_vps}` VPS\n🟢 `{running}` Running\n⛔ `{suspended}` Suspended\n✅ `{whitelisted}` Whitelisted', inline=True)
            embed.add_field(name='⚡ Quick Actions', value=f'`{PREFIX}manage`\n`{PREFIX}reinstall`\n`{PREFIX}status`', inline=True)
            embed.add_field(name='🧭 Tip', value='Use **manage** to control your VPS', inline=True)
            vps_text = '\n\n'.join(vps_cards)
            for i in range(0, len(vps_text), 1024):
                embed.add_field(name='🖥️ Your VPS', value=vps_text[i:i + 1024], inline=False)
            embed.set_footer(text=f'{BOT_NAME} • VPS Control Panel')
            embed.timestamp = ctx.message.created_at
            await ctx.send(embed=embed)
    @bot.command(name='lxc-list')
    @is_admin()
    async def lxc_list(ctx, node_id: int=1):
        # irreducible cflow, using cdg fallback
        try:
            result = await execute_lxc('', 'list', node_id=node_id)
            node = get_node(node_id)
            embed = create_info_embed(f"LXC Containers List on {node['name']}", result)
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=create_error_embed('Error', str(e)))
    class NodeSelectView(discord.ui.View):
        def __init__(self, ram: int, cpu: int, disk: int, user: discord.Member, ctx, days: int=7):
            super().__init__(timeout=300)
            self.ram = ram
            self.cpu = cpu
            self.disk = disk
            self.user = user
            self.ctx = ctx
            self.days = days
            nodes = get_nodes()
            options = []
            for n in nodes:
                current_count = get_current_vps_count(n['id'])
                if current_count < n['total_vps']:
                    options.append(discord.SelectOption(label=n['name'], value=str(n['id']), description=f"{n['location']} - Available: {n['total_vps'] - current_count}"))
            if not options:
                self.add_item(discord.ui.Select(placeholder='No available nodes', disabled=True))
            else:
                self.select = discord.ui.Select(placeholder='Select a Node for the VPS', options=options)
                self.select.callback = self.select_node
                self.add_item(self.select)
        async def select_node(self, interaction: discord.Interaction):
            if str(interaction.user.id)!= str(self.ctx.author.id):
                await interaction.response.send_message(embed=create_error_embed('Access Denied', 'Only the command author can select.'), ephemeral=True)
                return
            else:
                node_id = int(self.select.values[0])
                self.select.disabled = True
                await interaction.response.edit_message(view=self)
                os_view = OSSelectView(self.ram, self.cpu, self.disk, self.user, self.ctx, node_id, self.days)
                await interaction.followup.send(embed=create_info_embed('Select OS', 'Choose the OS for the VPS.'), view=os_view)
    class OSSelectView(discord.ui.View):
        def __init__(self, ram: int, cpu: int, disk: int, user: discord.Member, ctx, node_id: int, days: int=7):
            super().__init__(timeout=300)
            self.ram = ram
            self.cpu = cpu
            self.disk = disk
            self.user = user
            self.ctx = ctx
            self.node_id = node_id
            self.days = days
            self.select = discord.ui.Select(placeholder='Select an OS for the VPS', options=[discord.SelectOption(label=o['label'], value=o['value']) for o in OS_OPTIONS])
            self.select.callback = self.select_os
            self.add_item(self.select)
        async def select_os(self, interaction: discord.Interaction):
            # irreducible cflow, using cdg fallback
            if str(interaction.user.id)!= str(self.ctx.author.id):
                await interaction.response.send_message(embed=create_error_embed('Access Denied', 'Only the command author can select.'), ephemeral=True)
                return
            else:
                os_version = self.select.values[0]
                self.select.disabled = True
                creating_embed = create_info_embed('Creating VPS', f'Deploying {os_version} VPS for {self.user.mention} on node {self.node_id}...')
                await interaction.response.edit_message(embed=creating_embed, view=self)
                user_id = str(self.user.id)
                if user_id not in vps_data:
                    vps_data[user_id] = []
                vps_count = len(vps_data[user_id]) + 1
                container_name = f'{BOT_NAME.lower()}-vps-{user_id}-{vps_count}'
                ram_mb = self.ram * 1024
                await execute_lxc(container_name, f'init {os_version} {container_name} -s {DEFAULT_STORAGE_POOL}', node_id=self.node_id)
                await execute_lxc(container_name, f'config set {container_name} limits.memory {ram_mb}MB', node_id=self.node_id)
                await execute_lxc(container_name, f'config set {container_name} limits.cpu {self.cpu}', node_id=self.node_id)
                await execute_lxc(container_name, f'config device set {container_name} root size={self.disk}GB', node_id=self.node_id)
                await apply_lxc_config(container_name, self.node_id)
                await execute_lxc(container_name, f'start {container_name}', node_id=self.node_id)
                await apply_internal_permissions(container_name, self.node_id)
                await recreate_port_forwards(container_name)
                config_str = f'{self.ram}GB RAM / {self.cpu} CPU / {self.disk}GB Disk'
                expires_at = datetime.now() + timedelta(days=self.days)
                vps_info = {'container_name': container_name, 'node_id': self.node_id, 'ram': f'{self.ram}GB', 'cpu': str(self.cpu), 'storage': f'{self.disk}GB', 'config': config_str, 'os_version': os_version, 'status': 'running', 'suspended': False, 'whitelisted': False, 'suspension_history': [], 'created_at': datetime.now().isoformat(), 'shared_with': [], 'expires_at': expires_at.isoformat(), 'duration_days': self.days, 'auto_renew': 0, 'id': None}
                vps_data[user_id].append(vps_info)
                save_vps_data()
                if vps_info.get('id'):
                    set_vps_expiration(vps_info['id'], self.days)
                if self.ctx.guild:
                    vps_role = await get_or_create_vps_role(self.ctx.guild)
                    if vps_role:
                        try:
                            await self.user.add_roles(vps_role, reason=f'{BOT_NAME} VPS ownership granted')
                        except discord.Forbidden:
                            logger.warning(f'Failed to assign VPS role to {self.user.name}')
                renewal_cost = int(get_setting('coins_vps_renewal_1day', 50))
                success_embed = create_success_embed('VPS Created Successfully')
                add_field(success_embed, 'Owner', self.user.mention, True)
                add_field(success_embed, 'VPS ID', f'#{vps_count}', True)
                add_field(success_embed, 'Container', f'`{container_name}`', True)
                add_field(success_embed, 'Node', get_node(self.node_id)['name'], True)
                add_field(success_embed, 'Resources', f'**RAM:** {self.ram}GB\n**CPU:** {self.cpu} Cores\n**Storage:** {self.disk}GB', False)
                add_field(success_embed, 'OS', os_version, True)
                add_field(success_embed, '⏰ Expiration', f"**Expires:** {expires_at.strftime('%Y-%m-%d %H:%M')}\n**Duration:** {self.days} days\n**Renewal:** {renewal_cost} coins/day", True)
                add_field(success_embed, 'Features', 'Nesting, Privileged, FUSE, Kernel Modules (Docker Ready), Unprivileged Ports from 0', False)
                add_field(success_embed, 'Disk Note', 'Run `sudo resize2fs /` inside VPS if needed to expand filesystem.', False)
                await interaction.followup.send(embed=success_embed)
                dm_embed = create_success_embed('VPS Created!', 'Your VPS has been successfully deployed by an admin!')
                add_field(dm_embed, 'VPS Details', f"**VPS ID:** #{vps_count}\n**Container Name:** `{container_name}`\n**Configuration:** {config_str}\n**Status:** Running\n**OS:** {os_version}\n**Created:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", False)
                add_field(dm_embed, 'Management', f'• Use `{PREFIX}manage` to start/stop/reinstall your VPS\n• Use `{PREFIX}manage` → SSH for terminal access\n• Contact admin for upgrades or issues', False)
                add_field(dm_embed, 'Important Notes', '• Full root access via SSH\n• Docker-ready with nesting and privileged mode\n• Back up your data regularly', False)
                    await self.user.send(embed=dm_embed)
                        except discord.Forbidden:
                            await self.ctx.send(embed=create_info_embed('Notification Failed', f'Couldn\'t send DM to {self.user.mention}. Please ensure DMs are enabled.'))
                                return
                    except Exception as e:
                            error_embed = create_error_embed('Creation Failed', f'Error: {str(e)}')
                            await interaction.followup.send(embed=error_embed)
                                return
    @bot.command(name='create')
    @is_admin()
    async def create_vps(ctx, ram: int, cpu: int, disk: int, user: discord.Member, days: int=None):
        """Create a VPS with optional expiry days"""
        if ram <= 0 or cpu <= 0 or disk <= 0:
            await ctx.send(embed=create_error_embed('Invalid Specs', 'RAM, CPU, and Disk must be positive integers.'))
            return
        else:
            if days is None:
                days = int(get_setting('default_vps_duration_days', 7))
            else:
                if days < 1 or days > 365:
                    await ctx.send(embed=create_error_embed('Invalid Duration', 'Days must be between 1 and 365'))
                    return
            embed = create_info_embed('VPS Creation', f'Creating VPS for {user.mention}\n**Specs:** {ram}GB RAM, {cpu} CPU cores, {disk}GB Disk\n**Duration:** {days} days\nSelect node below.')
            view = NodeSelectView(ram, cpu, disk, user, ctx, days)
            await ctx.send(embed=embed, view=view)
    @bot.command(name='deploy', aliases=['deploy-vps', 'create-vps', 'buy-vps'])
    async def deploy_vps(ctx, plan_id: int=None):
        # irreducible cflow, using cdg fallback
        """Deploy your own VPS using coins - Use !deploy-plans to see available plans"""
        user_id = str(ctx.author.id)
        vps_list = vps_data.get(user_id, [])
        if len(vps_list) >= 1:
            await ctx.send(embed=create_error_embed('❌ VPS Limit Reached', f"You already have **{len(vps_list)} VPS**!\n\n**Limit:** 1 VPS per user\n**Your VPS:** `{vps_list[0]['container_name']}`\n\nUse `{PREFIX}manage` to control your existing VPS.\nContact an admin if you need additional VPS."))
            return
        else:
            if plan_id is None:
                await ctx.send(embed=create_info_embed('📋 Select a Plan', f'Please specify a deployment plan!\n\n**View Plans:** `{PREFIX}deploy-plans`\n**Deploy:** `{PREFIX}deploy <plan_id>`\n\n**Example:** `{PREFIX}deploy 2` (Basic plan)'))
                return
            else:
                plan = get_deploy_plan(plan_id)
                if not plan or not plan['active']:
                    await ctx.send(embed=create_error_embed('Invalid Plan', f'Plan #{plan_id} not found or inactive.\n\nUse `{PREFIX}deploy-plans` to see available plans.'))
                    return
                else:
                    ram = plan['ram_gb']
                    cpu = plan['cpu_cores']
                    disk = plan['disk_gb']
                    cost = plan['cost_coins']
                    default_days = plan['duration_days']
                    def check_balance():
                        coins_data = get_user_coins(user_id)
                        return (coins_data['balance'], coins_data)
                    balance, coins_data = await run_in_executor(check_balance)
                    if balance < cost:
                        needed = cost - balance
                        await ctx.send(embed=create_error_embed('💰 Insufficient Coins', f'You need **{cost:,} coins** to deploy a VPS.\n\n**Your Balance:** {balance:,} coins\n**You Need:** {needed:,} more coins\n\n**Earn Coins:**\n• `{PREFIX}daily` - Daily reward\n• `{PREFIX}work` - Work for coins\n• `{PREFIX}coinhelp` - More ways to earn'))
                    else:
                        embed = create_info_embed('🚀 Deploy Your VPS', f"You\'re about to deploy your own VPS!\n\n**Plan:** {plan['icon']} {plan['name']}\n**Specifications:**\n• **RAM:** {ram}GB\n• **CPU:** {cpu} Core{('s' if cpu > 1 else '')}\n• **Disk:** {disk}GB\n• **Duration:** {default_days} day{('s' if default_days > 1 else '')}\n\n**Cost:** {cost:,} coins\n**Your Balance:** {balance:,} coins\n**After Purchase:** {balance - cost:,} coins\n\n**Features:**\n• Full root access\n• Docker ready\n• SSH access\n• Port forwarding\n\nReact with ✅ to confirm or ❌ to cancel")
                        msg = await ctx.send(embed=embed)
                        await msg.add_reaction('✅')
                        await msg.add_reaction('❌')
                        def check(reaction, user):
                            return user == ctx.author and str(reaction.emoji) in ['✅', '❌'] and (reaction.message.id == msg.id)
            reaction, user = await bot.wait_for('reaction_add', timeout=60.0, check=check)
            if str(reaction.emoji) == '❌':
                await msg.edit(embed=create_info_embed('❌ Cancelled', 'VPS deployment cancelled.'))
                    return
                async def process_payment():
                    success, new_balance = remove_coins(user_id, cost, 'vps_purchase', f'Deployed VPS ({ram}GB RAM, {cpu} CPU, {disk}GB Disk)')
                    return (success, new_balance)
                success, new_balance = await run_in_executor(process_payment)
                if not success:
                    await msg.edit(embed=create_error_embed('❌ Payment Failed', 'Failed to process payment. Please try again.'))
                        return
                    await msg.edit(embed=create_info_embed('⏳ Deploying VPS', 'Your VPS is being deployed... This may take a moment.'))
                    nodes = get_nodes()
                    selected_node = None
                    for node in nodes:
                        current_count = get_current_vps_count(node['id'])
                        if current_count < node['total_vps']:
                            selected_node = node
                            break
                    if not selected_node:
                        add_coins(user_id, cost, 'refund', 'VPS deployment failed - no available nodes')
                        await msg.edit(embed=create_error_embed('❌ Deployment Failed', 'No available nodes. Your coins have been refunded.\nPlease contact an admin.'))
                            return
                        node_id = selected_node['id']
                        vps_count = 1
                        container_name = f'{BOT_NAME.lower()}-vps-{user_id}-{vps_count}'
                        ram_mb = ram * 1024
                        os_version = 'ubuntu:22.04'
                            await execute_lxc(container_name, f'init {os_version} {container_name} -s {DEFAULT_STORAGE_POOL}', node_id=node_id)
                            await execute_lxc(container_name, f'config set {container_name} limits.memory {ram_mb}MB', node_id=node_id)
                            await execute_lxc(container_name, f'config set {container_name} limits.cpu {cpu}', node_id=node_id)
                            await execute_lxc(container_name, f'config device set {container_name} root size={disk}GB', node_id=node_id)
                            await apply_lxc_config(container_name, node_id)
                            await execute_lxc(container_name, f'start {container_name}', node_id=node_id)
                            await apply_internal_permissions(container_name, node_id)
                            await recreate_port_forwards(container_name)
                            config_str = f'{ram}GB RAM / {cpu} CPU / {disk}GB Disk'
                            expires_at = datetime.now() + timedelta(days=default_days)
                            vps_info = {'container_name': container_name, 'node_id': node_id, 'ram': f'{ram}GB', 'cpu': str(cpu), 'storage': f'{disk}GB', 'config': config_str, 'os_version': os_version, 'status': 'running', 'suspended': False, 'whitelisted': False, 'suspension_history': [], 'created_at': datetime.now().isoformat(), 'shared_with': [], 'expires_at': expires_at.isoformat(), 'duration_days': default_days, 'auto_renew': 0, 'id': None}
                            if user_id not in vps_data:
                                vps_data[user_id] = []
                            vps_data[user_id].append(vps_info)
                            save_vps_data()
                            if ctx.guild:
                                vps_role = await get_or_create_vps_role(ctx.guild)
                                if vps_role:
                                    try:
                                        await ctx.author.add_roles(vps_role, reason=f'{BOT_NAME} VPS ownership granted')
                                    except discord.Forbidden:
                                        logger.warning(f'Failed to assign VPS role to {ctx.author.name}')
                            expiry_info = format_expiry_time(expires_at.isoformat())
                            renewal_cost = int(get_setting('coins_vps_renewal_1day', 50))
                            success_embed = create_success_embed('✅ VPS Deployed Successfully!', f"Your VPS is now running! 🎉\n\n**Container:** `{container_name}`\n**Node:** {selected_node['name']}\n**OS:** Ubuntu 22.04 LTS\n\n**Resources:**\n• RAM: {ram}GB\n• CPU: {cpu} Core\n• Disk: {disk}GB\n\n**Expiration:**\n• Expires: {expiry_info['text']}\n• Date: {expires_at.strftime('%Y-%m-%d %H:%M')}\n• Renewal: {renewal_cost} coins/day\n\n**Payment:**\n• Cost: {cost:,} coins\n• New Balance: {new_balance:,} coins")
                            add_field(success_embed, '🎮 Quick Start', f'`{PREFIX}manage` - Control your VPS\n`{PREFIX}manage` → SSH - Get terminal access\n`{PREFIX}renew 1 <days>` - Extend expiry', False)
                            add_field(success_embed, '💡 Important', '• Full root access via SSH\n• Docker-ready with nesting enabled\n• Back up your data regularly\n• Run `sudo resize2fs /` if needed', False)
                            await msg.edit(embed=success_embed)
                            logger.info(f'User {ctx.author.name} deployed VPS {container_name} for {cost} coins')
                                except Exception as e:
                                        add_coins(user_id, cost, 'refund', f'VPS deployment failed: {str(e)}')
                                        await msg.edit(embed=create_error_embed('❌ Deployment Failed', f'Failed to deploy VPS: {str(e)}\n\nYour {cost:,} coins have been refunded.\nPlease contact an admin for assistance.'))
                                        logger.error(f'VPS deployment failed for {ctx.author.name}: {e}')
                                            return
                except asyncio.TimeoutError:
                    await msg.edit(embed=create_info_embed('⏱️ Timeout', 'Deployment request timed out.'))
                        return
    @bot.command(name='deploy-plans', aliases=['plans', 'vps-plans'])
    async def show_deploy_plans(ctx):
        """Show available VPS deployment plans"""
        plans = get_deploy_plans(active_only=True)
        if not plans:
            await ctx.send(embed=create_error_embed('No Plans Available', 'No deployment plans are currently available. Contact an admin.'))
            return
        else:
            embed = create_info_embed('🚀 VPS Deployment Plans', 'Choose a plan and deploy your VPS!')
            for plan in plans:
                plan_info = f"**Resources:**\n• RAM: {plan['ram_gb']}GB\n• CPU: {plan['cpu_cores']} Core{('s' if plan['cpu_cores'] > 1 else '')}\n• Disk: {plan['disk_gb']}GB\n• Duration: {plan['duration_days']} day{('s' if plan['duration_days'] > 1 else '')}\n\n**Cost:** {plan['cost_coins']:,} coins\n**Deploy:** `{PREFIX}deploy {plan['id']}`"
                add_field(embed, f"{plan['icon']} {plan['name']}", plan_info, True)
            add_field(embed, '💡 How to Deploy', f'`{PREFIX}deploy <plan_id>`\nExample: `{PREFIX}deploy 2` (Basic plan)', False)
            embed.set_footer(text=f'{BOT_NAME} • Limit: 1 VPS per user')
            await ctx.send(embed=embed)
    @bot.command(name='resource-plans', aliases=['resources', 'upgrade-plans'])
    async def show_resource_plans(ctx):
        """Show available resource upgrade plans"""
        plans = get_resource_plans(active_only=True)
        if not plans:
            await ctx.send(embed=create_error_embed('No Plans Available', 'No resource plans are currently available. Contact an admin.'))
            return
        else:
            embed = create_info_embed('⚡ Resource Upgrade Plans', 'Upgrade your VPS to more powerful resources!')
            for plan in plans:
                plan_info = f"**New Resources:**\n• RAM: {plan['ram_gb']}GB\n• CPU: {plan['cpu_cores']} Core{('s' if plan['cpu_cores'] > 1 else '')}\n• Disk: {plan['disk_gb']}GB\n\n**Upgrade Cost:** {plan['upgrade_cost']:,} coins\n**Upgrade:** `{PREFIX}upgrade <vps_id> {plan['id']}`"
                add_field(embed, f"{plan['icon']} {plan['name']}", plan_info, True)
            add_field(embed, '💡 How to Upgrade', f'`{PREFIX}upgrade <vps_number> <plan_id>`\nExample: `{PREFIX}upgrade 1 3` (Upgrade VPS #1 to Medium)', False)
            add_field(embed, '📝 Note', 'Upgrades are permanent and cannot be downgraded.\nYour VPS will be restarted during the upgrade.', False)
            embed.set_footer(text=f'{BOT_NAME} • Instant resource upgrades')
            await ctx.send(embed=embed)
    @bot.command(name='upgrade', aliases=['upgrade-vps', 'vps-upgrade'])
    async def upgrade_vps(ctx, vps_number: int=None, plan_id: int=None):
        # irreducible cflow, using cdg fallback
        """Upgrade your VPS resources"""
        user_id = str(ctx.author.id)
        if vps_number is None or plan_id is None:
            await ctx.send(embed=create_error_embed('Usage', f'Usage: `{PREFIX}upgrade <vps_number> <plan_id>`\n\n**Example:** `{PREFIX}upgrade 1 3`\n**View Plans:** `{PREFIX}resource-plans`'))
            return
        else:
            vps_list = vps_data.get(user_id, [])
            if not vps_list:
                await ctx.send(embed=create_error_embed('No VPS Found', f'You don\'t have any VPS. Use `{PREFIX}deploy-plans` to create one.'))
                return
            else:
                if vps_number < 1 or vps_number > len(vps_list):
                    await ctx.send(embed=create_error_embed('Invalid VPS', f'You don\'t have VPS #{vps_number}. Use `{PREFIX}myvps` to see your VPS.'))
                    return
                else:
                    vps = vps_list[vps_number - 1]
                    plan = get_resource_plan(plan_id)
                    if not plan or not plan['active']:
                        await ctx.send(embed=create_error_embed('Invalid Plan', f'Plan #{plan_id} not found. Use `{PREFIX}resource-plans` to see available plans.'))
                        return
                    else:
                        current_ram = int(vps['ram'].replace('GB', ''))
                        current_cpu = int(vps['cpu'])
                        current_disk = int(vps['storage'].replace('GB', ''))
                        if plan['ram_gb'] <= current_ram and plan['cpu_cores'] <= current_cpu and (plan['disk_gb'] <= current_disk):
                            await ctx.send(embed=create_error_embed('No Upgrade Needed', f"Your VPS already has equal or better resources than the **{plan['name']}** plan.\n\n**Current:** {current_ram}GB RAM, {current_cpu} CPU, {current_disk}GB Disk\n**Plan:** {plan['ram_gb']}GB RAM, {plan['cpu_cores']} CPU, {plan['disk_gb']}GB Disk"))
                            return
                        else:
                            def check_balance():
                                coins_data = get_user_coins(user_id)
                                return (coins_data['balance'], coins_data)
                            balance, coins_data = await run_in_executor(check_balance)
                            cost = plan['upgrade_cost']
                            if balance < cost:
                                needed = cost - balance
                                await ctx.send(embed=create_error_embed('💰 Insufficient Coins', f"You need **{cost:,} coins** to upgrade to **{plan['name']}**.\n\n**Your Balance:** {balance:,} coins\n**You Need:** {needed:,} more coins\n\nUse `{PREFIX}coinhelp` to see how to earn coins!"))
                            else:
                                embed = create_warning_embed('⚡ Confirm VPS Upgrade', f"You\'re about to upgrade your VPS!\n\n**VPS:** `{vps['container_name']}`\n**Plan:** {plan['icon']} {plan['name']}\n\n**Current Resources:**\n• RAM: {current_ram}GB → **{plan['ram_gb']}GB**\n• CPU: {current_cpu} → **{plan['cpu_cores']}** Core{('s' if plan['cpu_cores'] > 1 else '')}\n• Disk: {current_disk}GB → **{plan['disk_gb']}GB**\n\n**Cost:** {cost:,} coins\n**Your Balance:** {balance:,} coins\n**After Upgrade:** {balance - cost:,} coins\n\n⚠️ **Warning:** VPS will be restarted during upgrade.\nReact with ✅ to confirm or ❌ to cancel")
                                msg = await ctx.send(embed=embed)
                                await msg.add_reaction('✅')
                                await msg.add_reaction('❌')
                                def check(reaction, user):
                                    return user == ctx.author and str(reaction.emoji) in ['✅', '❌'] and (reaction.message.id == msg.id)
            reaction, user = await bot.wait_for('reaction_add', timeout=60.0, check=check)
            if str(reaction.emoji) == '❌':
                await msg.edit(embed=create_info_embed('❌ Cancelled', 'VPS upgrade cancelled.'))
                    return
                def process_payment():
                    success, new_balance = remove_coins(user_id, cost, 'vps_upgrade', f"Upgraded VPS to {plan['name']} plan")
                    return (success, new_balance)
                success, new_balance = await run_in_executor(process_payment)
                if not success:
                    await msg.edit(embed=create_error_embed('❌ Payment Failed', 'Failed to process payment. Please try again.'))
                        return
                    await msg.edit(embed=create_info_embed('⏳ Upgrading VPS', 'Your VPS is being upgraded... This may take a moment.'))
                    container_name = vps['container_name']
                    node_id = vps['node_id']
                        await execute_lxc(container_name, f'stop {container_name}', timeout=120, node_id=node_id)
                        ram_mb = plan['ram_gb'] * 1024
                        await execute_lxc(container_name, f'config set {container_name} limits.memory {ram_mb}MB', node_id=node_id)
                        await execute_lxc(container_name, f"config set {container_name} limits.cpu {plan['cpu_cores']}", node_id=node_id)
                        await execute_lxc(container_name, f"config device set {container_name} root size={plan['disk_gb']}GB", node_id=node_id)
                        await execute_lxc(container_name, f'start {container_name}', node_id=node_id)
                        old_specs = {'ram': current_ram, 'cpu': current_cpu, 'disk': current_disk}
                        vps['ram'] = f"{plan['ram_gb']}GB"
                        vps['cpu'] = str(plan['cpu_cores'])
                        vps['storage'] = f"{plan['disk_gb']}GB"
                        vps['config'] = f"{plan['ram_gb']}GB RAM / {plan['cpu_cores']} CPU / {plan['disk_gb']}GB Disk"
                        save_vps_data()
                        new_specs = {'ram': plan['ram_gb'], 'cpu': plan['cpu_cores'], 'disk': plan['disk_gb']}
                        log_vps_upgrade(vps.get('id', 0), user_id, old_specs, new_specs, cost, user_id)
                        success_embed = create_success_embed('✅ VPS Upgraded Successfully!', f"Your VPS has been upgraded! 🎉\n\n**VPS:** `{container_name}`\n**Plan:** {plan['icon']} {plan['name']}\n\n**New Resources:**\n• RAM: {plan['ram_gb']}GB\n• CPU: {plan['cpu_cores']} Core{('s' if plan['cpu_cores'] > 1 else '')}\n• Disk: {plan['disk_gb']}GB\n\n**Cost:** {cost:,} coins\n**New Balance:** {new_balance:,} coins\n\nYour VPS is now running with upgraded resources!")
                        add_field(success_embed, '💡 Next Steps', f'• Run `sudo resize2fs /` inside VPS to expand filesystem\n• Use `{PREFIX}manage` to control your VPS\n• Check stats with `{PREFIX}status {container_name}`', False)
                        await msg.edit(embed=success_embed)
                        logger.info(f"User {ctx.author.name} upgraded VPS {container_name} to {plan['name']} for {cost} coins")
                            except Exception as e:
                                    add_coins(user_id, cost, 'refund', f'VPS upgrade failed: {str(e)}')
                                    await msg.edit(embed=create_error_embed('❌ Upgrade Failed', f'Failed to upgrade VPS: {str(e)}\n\nYour {cost:,} coins have been refunded.\nPlease contact an admin for assistance.'))
                                    logger.error(f'VPS upgrade failed for {ctx.author.name}: {e}')
                                        return
                except asyncio.TimeoutError:
                    await msg.edit(embed=create_info_embed('⏱️ Timeout', 'Upgrade request timed out.'))
                        return
    class ReinstallOSSelectView(discord.ui.View):
        def __init__(self, parent_view, container_name, owner_id, actual_idx, ram_gb, cpu, storage_gb, node_id):
            super().__init__(timeout=300)
            self.parent_view = parent_view
            self.container_name = container_name
            self.owner_id = owner_id
            self.actual_idx = actual_idx
            self.ram_gb = ram_gb
            self.cpu = cpu
            self.storage_gb = storage_gb
            self.node_id = node_id
            self.select = discord.ui.Select(placeholder='Select an OS for the reinstall', options=[discord.SelectOption(label=o['label'], value=o['value']) for o in OS_OPTIONS])
            self.select.callback = self.select_os
            self.add_item(self.select)
        async def select_os(self, interaction: discord.Interaction):
            os_version = self.select.values[0]
            self.select.disabled = True
            creating_embed = create_info_embed('Reinstalling VPS', f'Deploying {os_version} for `{self.container_name}`...')
            await interaction.response.edit_message(embed=creating_embed, view=self)
            ram_mb = self.ram_gb * 1024
            try:
                await execute_lxc(self.container_name, f'init {os_version} {self.container_name} -s {DEFAULT_STORAGE_POOL}', node_id=self.node_id)
                await execute_lxc(self.container_name, f'config set {self.container_name} limits.memory {ram_mb}MB', node_id=self.node_id)
                await execute_lxc(self.container_name, f'config set {self.container_name} limits.cpu {self.cpu}', node_id=self.node_id)
                await execute_lxc(self.container_name, f'config device set {self.container_name} root size={self.storage_gb}GB', node_id=self.node_id)
                await apply_lxc_config(self.container_name, self.node_id)
                await execute_lxc(self.container_name, f'start {self.container_name}', node_id=self.node_id)
                await apply_internal_permissions(self.container_name, self.node_id)
                await recreate_port_forwards(self.container_name)
                target_vps = vps_data[self.owner_id][self.actual_idx]
                target_vps['os_version'] = os_version
                target_vps['status'] = 'running'
                target_vps['suspended'] = False
                target_vps['created_at'] = datetime.now().isoformat()
                config_str = f'{self.ram_gb}GB RAM / {self.cpu} CPU / {self.storage_gb}GB Disk'
                target_vps['config'] = config_str
                save_vps_data()
                success_embed = create_success_embed('Reinstall Complete', f'VPS `{self.container_name}` has been successfully reinstalled!')
                add_field(success_embed, 'Resources', f'**RAM:** {self.ram_gb}GB\n**CPU:** {self.cpu} Cores\n**Storage:** {self.storage_gb}GB', False)
                add_field(success_embed, 'OS', os_version, True)
                add_field(success_embed, 'Features', 'Nesting, Privileged, FUSE, Kernel Modules (Docker Ready), Unprivileged Ports from 0', False)
                add_field(success_embed, 'Disk Note', 'Run `sudo resize2fs /` inside VPS if needed to expand filesystem.', False)
                await interaction.followup.send(embed=success_embed, ephemeral=True)
                self.stop()
            except Exception as e:
                error_embed = create_error_embed('Reinstall Failed', f'Error: {str(e)}')
                await interaction.followup.send(embed=error_embed, ephemeral=True)
                self.stop()
    class ManageView(discord.ui.View):
        def __init__(self, user_id, vps_list, is_shared=False, owner_id=None, is_admin=False, actual_index: Optional[int]=None):
            super().__init__(timeout=300)
            self.user_id = user_id
            self.vps_list = vps_list[:]
            self.selected_index = None
            self.is_shared = is_shared
            self.owner_id = owner_id or user_id
            self.is_admin = is_admin
            self.actual_index = actual_index
            self.indices = list(range(len(vps_list)))
            if self.is_shared and self.actual_index is None:
                raise ValueError('actual_index required for shared views')
            else:
                if len(vps_list) > 1:
                    options = [discord.SelectOption(label=f"VPS {i + 1} ({v.get('config', 'Custom')})", description=f"Status: {v.get('status', 'unknown')}", value=str(i)) for i, v in enumerate(vps_list)]
                    self.select = discord.ui.Select(placeholder='Select a VPS to manage', options=options)
                    self.select.callback = self.select_vps
                    self.add_item(self.select)
                    self.initial_embed = create_embed('VPS Management', 'Select a VPS from the dropdown menu below.', 1710618)
                    add_field(self.initial_embed, 'Available VPS', '\n'.join([f"**VPS {i + 1}:** `{v['container_name']}` - Status: `{v.get('status', 'unknown').upper()}`" for i, v in enumerate(vps_list)]), False)
                else:
                    self.selected_index = 0
                    self.initial_embed = None
                    self.add_action_buttons()
        async def get_initial_embed(self):
            if self.initial_embed is not None:
                return self.initial_embed
            else:
                self.initial_embed = await self.create_vps_embed(self.selected_index)
                return self.initial_embed
        async def create_vps_embed(self, index):
            vps = self.vps_list[index]
            node = get_node(vps['node_id'])
            node_name = node['name'] if node else 'Unknown'
            status = vps.get('status', 'unknown')
            suspended = vps.get('suspended', False)
            whitelisted = vps.get('whitelisted', False)
            status_color = 65416 if status == 'running' and (not suspended) else 16755200 if suspended else 16724838
            container_name = vps['container_name']
            stats = await get_container_stats(container_name)
            status_text = f"{stats['status'].upper()}"
            if suspended:
                status_text += ' (SUSPENDED)'
            if whitelisted:
                status_text += ' (WHITELISTED)'
            owner_text = ''
            if self.is_admin and self.owner_id!= self.user_id:
                    try:
                        owner_user = await bot.fetch_user(int(self.owner_id))
                        owner_text = f'\n**Owner:** {owner_user.mention}'
                    except:
                        owner_text = f'\n**Owner ID:** {self.owner_id}'
            embed = create_embed(f'VPS Management - VPS {index + 1}', f'Managing container: `{container_name}` on node {node_name}{owner_text}', status_color)
            resource_info = f"**Configuration:** {vps.get('config', 'Custom')}\n"
            resource_info += f'**Status:** `{status_text}`\n'
            resource_info += f"**RAM:** {vps['ram']}\n"
            resource_info += f"**CPU:** {vps['cpu']} Cores\n"
            resource_info += f"**Storage:** {vps['storage']}\n"
            resource_info += f"**OS:** {vps.get('os_version', 'ubuntu:22.04')}\n"
            resource_info += f"**Uptime:** {stats['uptime']}"
            add_field(embed, '📊 Allocated Resources', resource_info, False)
            expiry_info = format_expiry_time(vps.get('expires_at'))
            add_field(embed, '⏰ Expiration', expiry_info['text'], True)
            if expiry_info['status'] in ['warning', 'critical', 'urgent']:
                add_field(embed, '💡 Renew', f"`{PREFIX}renew {vps.get('id', '?')} <days>`", True)
            if suspended:
                add_field(embed, '⚠️ Suspended', 'This VPS is suspended. Contact an admin to unsuspend.', False)
            if whitelisted:
                add_field(embed, '✅ Whitelisted', 'This VPS is exempt from auto-suspension.', False)
            live_stats = f"**CPU Usage:** {stats['cpu']:.1f}%\n**Memory:** {stats['ram']['used']}/{stats['ram']['total']} MB ({stats['ram']['pct']:.1f}%)\n**Disk:** {stats['disk']}"
            add_field(embed, '📈 Live Usage', live_stats, False)
            add_field(embed, '🎮 Controls', 'Use the buttons below to manage your VPS', False)
            return embed
        def add_action_buttons(self):
            if not self.is_shared and (not self.is_admin):
                    reinstall_button = discord.ui.Button(label='🔄 Reinstall', style=discord.ButtonStyle.danger)
                    reinstall_button.callback = lambda inter: self.action_callback(inter, 'reinstall')
                    self.add_item(reinstall_button)
            start_button = discord.ui.Button(label='▶ Start', style=discord.ButtonStyle.success)
            start_button.callback = lambda inter: self.action_callback(inter, 'start')
            stop_button = discord.ui.Button(label='⏸ Stop', style=discord.ButtonStyle.secondary)
            stop_button.callback = lambda inter: self.action_callback(inter, 'stop')
            ssh_button = discord.ui.Button(label='🔑 SSH', style=discord.ButtonStyle.primary)
            ssh_button.callback = lambda inter: self.action_callback(inter, 'tmate')
            stats_button = discord.ui.Button(label='📊 Stats', style=discord.ButtonStyle.secondary)
            stats_button.callback = lambda inter: self.action_callback(inter, 'stats')
            self.add_item(start_button)
            self.add_item(stop_button)
            self.add_item(ssh_button)
            self.add_item(stats_button)
        async def select_vps(self, interaction: discord.Interaction):
            if str(interaction.user.id)!= self.user_id and (not self.is_admin):
                await interaction.response.send_message(embed=create_error_embed('Access Denied', 'This is not your VPS!'), ephemeral=True)
                return
            else:
                self.selected_index = int(self.select.values[0])
                await interaction.response.defer()
                new_embed = await self.create_vps_embed(self.selected_index)
                self.clear_items()
                self.add_action_buttons()
                await interaction.edit_original_response(embed=new_embed, view=self)
        async def action_callback(self, interaction: discord.Interaction, action: str):
            # irreducible cflow, using cdg fallback
            if str(interaction.user.id)!= self.user_id and (not self.is_admin):
                await interaction.response.send_message(embed=create_error_embed('Access Denied', 'This is not your VPS!'), ephemeral=True)
                return
            if self.selected_index is None:
                await interaction.response.send_message(embed=create_error_embed('No VPS Selected', 'Please select a VPS first.'), ephemeral=True)
                return
            actual_idx = self.actual_index if self.is_shared else self.indices[self.selected_index]
            target_vps = vps_data[self.owner_id][actual_idx]
            suspended = target_vps.get('suspended', False)
            if suspended and (not self.is_admin) and (action!= 'stats'):
                await interaction.response.send_message(embed=create_error_embed('Access Denied', 'This VPS is suspended. Contact an admin to unsuspend.'), ephemeral=True)
                return
            container_name = target_vps['container_name']
            node_id = target_vps['node_id']
            if action == 'stats':
                stats = await get_container_stats(container_name, node_id)
                stats_embed = create_info_embed('📈 Live Statistics', f'Real-time stats for `{container_name}`')
                add_field(stats_embed, 'Status', f"`{stats['status'].upper()}`", True)
                add_field(stats_embed, 'CPU', f"{stats['cpu']:.1f}%", True)
                add_field(stats_embed, 'Memory', f"{stats['ram']['used']}/{stats['ram']['total']} MB ({stats['ram']['pct']:.1f}%)", True)
                add_field(stats_embed, 'Disk', stats['disk'], True)
                add_field(stats_embed, 'Uptime', stats['uptime'], True)
                await interaction.response.send_message(embed=stats_embed, ephemeral=True)
            if action == 'reinstall':
                if self.is_shared or self.is_admin:
                    await interaction.response.send_message(embed=create_error_embed('Access Denied', 'Only the VPS owner can reinstall!'), ephemeral=True)
                else:
                    if suspended:
                        await interaction.response.send_message(embed=create_error_embed('Cannot Reinstall', 'Unsuspend the VPS first.'), ephemeral=True)
                        return
                    else:
                        ram_gb = int(target_vps['ram'].replace('GB', ''))
                        cpu = int(target_vps['cpu'])
                        storage_gb = int(target_vps['storage'].replace('GB', ''))
                        confirm_embed = create_warning_embed('Reinstall Warning', f'⚠️ **WARNING:** This will erase all data on VPS `{container_name}` and reinstall a fresh OS.\n\nThis action cannot be undone. Continue?')
                        class ConfirmView(discord.ui.View):
                            def __init__(self, parent_view, container_name, owner_id, actual_idx, ram_gb, cpu, storage_gb, node_id):
                                super().__init__(timeout=60)
                                self.parent_view = parent_view
                                self.container_name = container_name
                                self.owner_id = owner_id
                                self.actual_idx = actual_idx
                                self.ram_gb = ram_gb
                                self.cpu = cpu
                                self.storage_gb = storage_gb
                                self.node_id = node_id
                            @discord.ui.button(label='Confirm', style=discord.ButtonStyle.danger)
                            async def confirm(self, inter: discord.Interaction, item: discord.ui.Button):
                                await inter.response.defer(ephemeral=True)
                                try:
                                    await inter.followup.send(embed=create_info_embed('Deleting Container', f'Forcefully removing container `{self.container_name}`...'), ephemeral=True)
                                    await execute_lxc(self.container_name, f'delete {self.container_name} --force', node_id=self.node_id)
                                    os_view = ReinstallOSSelectView(self.parent_view, self.container_name, self.owner_id, self.actual_idx, self.ram_gb, self.cpu, self.storage_gb, self.node_id)
                                    await inter.followup.send(embed=create_info_embed('Select OS', 'Choose the new OS for reinstallation.'), view=os_view, ephemeral=True)
                                except Exception as e:
                                    await inter.followup.send(embed=create_error_embed('Delete Failed', f'Error: {str(e)}'), ephemeral=True)
                                    return
                            @discord.ui.button(label='Cancel', style=discord.ButtonStyle.secondary)
                            async def cancel(self, inter: discord.Interaction, item: discord.ui.Button):
                                new_embed = await self.parent_view.create_vps_embed(self.parent_view.selected_index)
                                await inter.response.edit_message(embed=new_embed, view=self.parent_view)
                        await interaction.response.send_message(embed=confirm_embed, view=ConfirmView(self, container_name, self.owner_id, actual_idx, ram_gb, cpu, storage_gb, node_id), ephemeral=True)
            await interaction.response.defer(ephemeral=True)
            suspended = target_vps.get('suspended', False)
            if suspended:
                target_vps['suspended'] = False
                save_vps_data()
            if action == 'start':
                try:
                    await execute_lxc(container_name, f'start {container_name}', node_id=node_id)
                    target_vps['status'] = 'running'
                    save_vps_data()
                    await apply_internal_permissions(container_name, node_id)
                    readded = await recreate_port_forwards(container_name)
                    await interaction.followup.send(embed=create_success_embed('VPS Started', f'VPS `{container_name}` is now running! Re-added {readded} port forwards.'), ephemeral=True)
                except Exception as e:
                    await interaction.followup.send(embed=create_error_embed('Start Failed', str(e)), ephemeral=True)
                else:
                    pass
                if action == 'stop':
                    try:
                        await execute_lxc(container_name, f'stop {container_name}', timeout=120, node_id=node_id)
                        target_vps['status'] = 'stopped'
                        save_vps_data()
                        await interaction.followup.send(embed=create_success_embed('VPS Stopped', f'VPS `{container_name}` has been stopped!'), ephemeral=True)
                    except Exception as e:
                        await interaction.followup.send(embed=create_error_embed('Stop Failed', str(e)), ephemeral=True)
                    else:
                        pass
                    if action == 'tmate':
                        if suspended:
                            await interaction.followup.send(embed=create_error_embed('Access Denied', 'Cannot access suspended VPS.'), ephemeral=True)
                            return
                        else:
                            await interaction.followup.send(embed=create_info_embed('SSH Access', 'Generating SSH connection...'), ephemeral=True)
                            try:
                                await execute_lxc(container_name, f'exec {container_name} -- which tmate', node_id=node_id)
                            except:
                                await interaction.followup.send(embed=create_info_embed('Installing SSH', 'Installing tmate...'), ephemeral=True)
                                await execute_lxc(container_name, f'exec {container_name} -- apt-get update -y', node_id=node_id)
                                await execute_lxc(container_name, f'exec {container_name} -- apt-get install tmate -y', node_id=node_id)
                                await interaction.followup.send(embed=create_success_embed('Installed', 'SSH service installed!'), ephemeral=True)
                            session_name = f"{BOT_NAME.lower()}-session-{datetime.now().strftime('%Y%m%d%H%M%S')}"
                            await execute_lxc(container_name, f'exec {container_name} -- tmate -S /tmp/{session_name}.sock new-session -d', node_id=node_id)
                            await asyncio.sleep(3)
                            ssh_output = await execute_lxc(container_name, f'exec {container_name} -- tmate -S /tmp/{session_name}.sock display -p \'#{tmate_ssh}\'', node_id=node_id)
                            ssh_url = ssh_output.strip()
                            if ssh_url:
                                try:
                                    ssh_embed = create_embed('🔑 SSH Access', f'SSH connection for VPS `{container_name}`:', 65416)
                                    add_field(ssh_embed, 'Command', f'```{ssh_url}```', False)
                                    add_field(ssh_embed, '⚠️ Security', 'This link is temporary. Do not share it.', False)
                                    add_field(ssh_embed, '📝 Session', f'Session ID: {session_name}', False)
                                    await interaction.user.send(embed=ssh_embed)
                                    await interaction.followup.send(embed=create_success_embed('SSH Sent', f'Check your DMs for SSH link! Session: {session_name}'), ephemeral=True)
                                except discord.Forbidden:
                                    await interaction.followup.send(embed=create_error_embed('DM Failed', 'Enable DMs to receive SSH link!'), ephemeral=True)
                                else:
                                    pass
                            else:
                                await interaction.followup.send(embed=create_error_embed('SSH Failed', 'No SSH URL generated.'), ephemeral=True)
                        new_embed = await self.create_vps_embed(self.selected_index)
                        await interaction.edit_original_response(embed=new_embed, view=self)
                                except Exception as e:
                                        await interaction.followup.send(embed=create_error_embed('SSH Error', str(e)), ephemeral=True)
    @bot.command(name='manage')
    async def manage_vps(ctx, user: discord.Member=None):
        if user:
            if str(ctx.author.id)!= str(MAIN_ADMIN_ID) and str(ctx.author.id) not in admin_data.get('admins', []):
                await ctx.send(embed=create_error_embed('Access Denied', 'Only admins can manage other users\' VPS.'))
                return
            else:
                user_id = str(user.id)
                vps_list = vps_data.get(user_id, [])
                if not vps_list:
                    await ctx.send(embed=create_error_embed('No VPS Found', f'{user.mention} doesn\'t have any {BOT_NAME} VPS.'))
                    return
                else:
                    view = ManageView(str(ctx.author.id), vps_list, is_admin=True, owner_id=user_id)
                    await ctx.send(embed=create_info_embed(f'Managing {user.name}\'s VPS', f'Managing VPS for {user.mention}'), view=view)
                    return
        else:
            user_id = str(ctx.author.id)
            vps_list = vps_data.get(user_id, [])
            if not vps_list:
                embed = create_error_embed('No VPS Found', f'You don\'t have any {BOT_NAME} VPS. Contact an admin to create one.')
                add_field(embed, 'Quick Actions', f'• `{PREFIX}manage` - Manage VPS\n• Contact admin for VPS creation', False)
                await ctx.send(embed=embed)
                return
            else:
                view = ManageView(user_id, vps_list)
                embed = await view.get_initial_embed()
                await ctx.send(embed=embed, view=view)
    async def get_node_status(node_id: int) -> str:
        # irreducible cflow, using cdg fallback
        node = get_node(node_id)
        if not node:
            return '❓ Unknown'
        else:
            if node['is_local']:
                return '🟢 Online (Local)'
            response = requests.get(f"{node['url']}/api/ping", params={'api_key': node['api_key']}, timeout=5)
            if response.status_code == 200:
                return '🟢 Online'
                return '🔴 Offline'
                except Exception as e:
                        logger.error(f"Failed to ping node {node['name']}: {e}")
                            return '🔴 Offline'
    def get_host_disk_usage():
        # irreducible cflow, using cdg fallback
        """Get host disk usage - cross-platform"""
        import psutil
        if os.name == 'nt':
            disk = psutil.disk_usage('C:\\')
        else:
            disk = psutil.disk_usage('/')
        total_gb = disk.total / 1073741824
        used_gb = disk.used / 1073741824
        percent = disk.percent
        return f'{used_gb:.1f}GB/{total_gb:.1f}GB ({percent}%)'
            except ImportError:
                    pass
                    if shutil.which('df'):
                        result = subprocess.run(['df', '-h', '/'], capture_output=True, text=True)
                        lines = result.stdout.splitlines()
                        if len(lines) > 1:
                            parts = lines[1].split()
                            total = parts[1]
                            used = parts[2]
                            perc = parts[4]
                            return f'{used}/{total} ({perc})'
                        return 'Unknown'
                        except Exception as e:
                                logger.error(f'Error getting disk usage: {e}')
                                    return 'Unknown'
                                        pass
    async def get_host_stats(node_id: int) -> Dict:
        # irreducible cflow, using cdg fallback
        node = get_node(node_id)
        if node['is_local']:
            return {'cpu': get_host_cpu_usage(), 'ram': get_host_ram_usage(), 'disk': get_host_disk_usage()}
        else:
            url = f"{node['url']}/api/get_host_stats"
            params = {'api_key': node['api_key']}
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            stats = response.json()
            stats['disk'] = stats.get('disk', 'Unknown')
            return stats
                except Exception as e:
                        logger.error(f"Failed to get host stats from node {node['name']}: {e}")
                        return {'cpu': 0.0, 'ram': 0.0, 'disk': 'Unknown'}
    @bot.command(name='vps-list')
    @is_admin()
    async def vps_list(ctx, node_id: int=1):
        node = get_node(node_id)
        if not node:
            await ctx.send(embed=create_error_embed('Node Not Found', f'Node ID {node_id} not found.'))
            return
        else:
            status = await get_node_status(node_id)
            is_online = status.startswith('🟢')
            stats = await get_host_stats(node_id)
            cpu_usage = stats.get('cpu', 0.0)
            ram_usage = stats.get('ram', 0.0)
            disk_usage = stats.get('disk', 'Unknown')
            if is_online:
                resources_text = f"**CPU** {cpu_usage:.0f}% {'█' * int(cpu_usage / 5) + '░' * (20 - int(cpu_usage / 5))} \n**RAM** {ram_usage:.0f}% {'█' * int(ram_usage / 5) + '░' * (20 - int(ram_usage / 5))} \n**Disk** {disk_usage}"
            else:
                resources_text = '⚠️ Resources unavailable (Offline)'
            current_vps = get_current_vps_count(node_id)
            total_capacity = node['total_vps']
            capacity_percent = current_vps / total_capacity * 100 if total_capacity > 0 else 0
            capacity_text = f'{current_vps}/{total_capacity} ({capacity_percent:.0f}%)'
            conn = get_db()
            cur = conn.cursor()
            cur.execute('SELECT * FROM vps WHERE node_id = ?', (node_id,))
            rows = cur.fetchall()
            conn.close()
            total_vps = len(rows)
            running = 0
            stopped = 0
            suspended = 0
            other = 0
            vps_info = []
            for i, row in enumerate(rows, 1):
                vps = dict(row)
                user_id = vps['user_id']
                try:
                    user = await bot.fetch_user(int(user_id))
                    username = user.name
                except:
                    username = f'Unknown ({user_id})'
                status = vps.get('status', 'unknown')
                suspended_flag = vps.get('suspended', False)
                if suspended_flag:
                    suspended += 1
                else:
                    if status == 'running':
                        running += 1
                    else:
                        if status == 'stopped':
                            stopped += 1
                        else:
                            other += 1
                status_emoji = '🟢' if status == 'running' and (not suspended_flag) else '🟡' if suspended_flag else '🔴'
                vps_status = status.upper()
                if suspended_flag:
                    vps_status += ' (SUSPENDED)'
                if vps.get('whitelisted', False):
                    vps_status += ' (WHITELISTED)'
                config = vps.get('config', 'Custom')
                vps_info.append(f"{status_emoji} **{i}.** {username} • `{vps['container_name']}`\n _{vps_status} | {config}_")
            color = 1096065 if is_online else 15680580
            embed = create_embed(title=f"🖥️ VPS Dashboard - {node['name']}", description=f"**ID:** `{node_id}` | **Region:** {node['location']}\n*Updated: <t:{int(datetime.now().timestamp())}:R>*", color=color)
            embed.set_thumbnail(url=node.get('thumbnail_url', None))
            add_field(embed, '📡 **Status**', status, True)
            add_field(embed, '🗄️ **Capacity**', capacity_text, True)
            add_field(embed, '📊 **Resources**', resources_text, False)
            summary_text = f'**Total:** {total_vps} 📊\n**Running:** {running} 🟢\n**Stopped:** {stopped} ⏸️\n**Suspended:** {suspended} 🟡'
            if other > 0:
                summary_text += f'\n**Other:** {other} ⚠️'
            add_field(embed, '📈 **Summary**', summary_text, True)
            if vps_info:
                chunk_size = 6
                chunks = [vps_info[i:i + chunk_size] for i in range(0, len(vps_info), chunk_size)]
                first_chunk_text = '\n'.join(chunks[0])
                add_field(embed, '📋 **Active VPS (1/{len(chunks)})**', f'```{first_chunk_text}```', False)
                for idx, chunk in enumerate(chunks[1:], 2):
                    page_embed = create_embed(title=f"🖥️ VPS Dashboard - {node['name']} (Page {idx}/{len(chunks)})", description=f"**ID:** `{node_id}` | **Region:** {node['location']}\n*Updated: <t:{int(datetime.now().timestamp())}:R>*", color=color)
                    chunk_text = '\n'.join(chunk)
                    add_field(page_embed, '📋 **VPS List**', f'```{chunk_text}```', False)
                    page_embed.set_footer(text=f'Total: {total_vps} VPS | Powered by Your Bot')
                    await ctx.send(embed=page_embed)
            else:
                add_field(embed, '📋 **VPS List**', 'No deployments yet. Launch one! 🚀', False)
            embed.set_footer(text=f'Refresh with !vps-list {node_id} | {len(vps_info)} shown')
            await ctx.send(embed=embed)
    @bot.command(name='list-all')
    @is_admin()
    async def list_all_vps(ctx):
        total_vps = 0
        total_users = len(vps_data)
        running_vps = 0
        stopped_vps = 0
        suspended_vps = 0
        whitelisted_vps = 0
        vps_info = []
        user_summary = []
        for user_id, vps_list in vps_data.items():
            try:
                user = await bot.fetch_user(int(user_id))
                user_vps_count = len(vps_list)
                user_running = sum((1 for vps in vps_list if vps.get('status') == 'running' and (not vps.get('suspended', False))))
                user_stopped = sum((1 for vps in vps_list if vps.get('status') == 'stopped'))
                user_suspended = sum((1 for vps in vps_list if vps.get('suspended', False)))
                user_whitelisted = sum((1 for vps in vps_list if vps.get('whitelisted', False)))
                total_vps += user_vps_count
                running_vps += user_running
                stopped_vps += user_stopped
                suspended_vps += user_suspended
                whitelisted_vps += user_whitelisted
                user_summary.append(f'**{user.name}** ({user.mention}) - {user_vps_count} VPS ({user_running} running, {user_suspended} suspended, {user_whitelisted} whitelisted)')
                for i, vps in enumerate(vps_list):
                    node = get_node(vps['node_id'])
                    node_name = node['name'] if node else 'Unknown'
                    status_emoji = '🟢' if vps.get('status') == 'running' and (not vps.get('suspended', False)) else '🟡' if vps.get('suspended', False) else '🔴'
                    status_text = vps.get('status', 'unknown').upper()
                    if vps.get('suspended', False):
                        status_text += ' (SUSPENDED)'
                    if vps.get('whitelisted', False):
                        status_text += ' (WHITELISTED)'
                    vps_info.append(f"{status_emoji} **{user.name}** - VPS {i + 1}: `{vps['container_name']}` - {vps.get('config', 'Custom')} - {status_text} (Node: {node_name})")
            except discord.NotFound:
                vps_info.append(f'❓ Unknown User ({user_id}) - {len(vps_list)} VPS')
                pass
            else:
                pass
        embed = create_embed('All VPS Information', 'Complete overview of all VPS deployments and user statistics', 1710618)
        add_field(embed, 'System Overview', f'**Total Users:** {total_users}\n**Total VPS:** {total_vps}\n**Running:** {running_vps}\n**Stopped:** {stopped_vps}\n**Suspended:** {suspended_vps}\n**Whitelisted:** {whitelisted_vps}', False)
        await ctx.send(embed=embed)
        if user_summary:
            embed = create_embed('User Summary', 'Summary of all users and their VPS', 1710618)
            summary_text = '\n'.join(user_summary)
            chunks = [summary_text[i:i + 1024] for i in range(0, len(summary_text), 1024)]
            for idx, chunk in enumerate(chunks, 1):
                add_field(embed, f'Users (Part {idx})', chunk, False)
            await ctx.send(embed=embed)
        if vps_info:
            vps_text = '\n'.join(vps_info)
            chunks = [vps_text[i:i + 1024] for i in range(0, len(vps_text), 1024)]
            for idx, chunk in enumerate(chunks, 1):
                embed = create_embed(f'VPS Details (Part {idx})', 'List of all VPS deployments', 1710618)
                add_field(embed, 'VPS List', chunk, False)
                await ctx.send(embed=embed)
    @bot.command(name='manage-shared')
    async def manage_shared_vps(ctx, owner: discord.Member, vps_number: int):
        owner_id = str(owner.id)
        user_id = str(ctx.author.id)
        if owner_id not in vps_data or vps_number < 1 or vps_number > len(vps_data[owner_id]):
            await ctx.send(embed=create_error_embed('Invalid VPS', 'Invalid VPS number or owner doesn\'t have a VPS.'))
            return
        else:
            vps = vps_data[owner_id][vps_number - 1]
            if user_id not in vps.get('shared_with', []):
                await ctx.send(embed=create_error_embed('Access Denied', 'You do not have access to this VPS.'))
                return
            else:
                view = ManageView(user_id, [vps], is_shared=True, owner_id=owner_id, actual_index=vps_number - 1)
                embed = await view.get_initial_embed()
                await ctx.send(embed=embed, view=view)
    @bot.command(name='share-user')
    async def share_user(ctx, shared_user: discord.Member, vps_number: int):
        user_id = str(ctx.author.id)
        shared_user_id = str(shared_user.id)
        if user_id not in vps_data or vps_number < 1 or vps_number > len(vps_data[user_id]):
            await ctx.send(embed=create_error_embed('Invalid VPS', 'Invalid VPS number or you don\'t have a VPS.'))
            return
        else:
            vps = vps_data[user_id][vps_number - 1]
            if 'shared_with' not in vps:
                vps['shared_with'] = []
            if shared_user_id in vps['shared_with']:
                await ctx.send(embed=create_error_embed('Already Shared', f'{shared_user.mention} already has access to this VPS!'))
                return
            else:
                vps['shared_with'].append(shared_user_id)
                save_vps_data()
                await ctx.send(embed=create_success_embed('VPS Shared', f'VPS #{vps_number} shared with {shared_user.mention}!'))
                try:
                    await shared_user.send(embed=create_embed('VPS Access Granted', f'You have access to VPS #{vps_number} from {ctx.author.mention}. Use `{PREFIX}manage-shared {ctx.author.mention} {vps_number}`', 65416))
                except discord.Forbidden:
                    await ctx.send(embed=create_info_embed('Notification Failed', f'Could not DM {shared_user.mention}'))
                    return
    @bot.command(name='share-ruser')
    async def revoke_share(ctx, shared_user: discord.Member, vps_number: int):
        user_id = str(ctx.author.id)
        shared_user_id = str(shared_user.id)
        if user_id not in vps_data or vps_number < 1 or vps_number > len(vps_data[user_id]):
            await ctx.send(embed=create_error_embed('Invalid VPS', 'Invalid VPS number or you don\'t have a VPS.'))
            return
        else:
            vps = vps_data[user_id][vps_number - 1]
            if 'shared_with' not in vps:
                vps['shared_with'] = []
            if shared_user_id not in vps['shared_with']:
                await ctx.send(embed=create_error_embed('Not Shared', f'{shared_user.mention} doesn\'t have access to this VPS!'))
                return
            else:
                vps['shared_with'].remove(shared_user_id)
                save_vps_data()
                await ctx.send(embed=create_success_embed('Access Revoked', f'Access to VPS #{vps_number} revoked from {shared_user.mention}!'))
                try:
                    await shared_user.send(embed=create_embed('VPS Access Revoked', f'Your access to VPS #{vps_number} by {ctx.author.mention} has been revoked.', 16724838))
                except discord.Forbidden:
                    await ctx.send(embed=create_info_embed('Notification Failed', f'Could not DM {shared_user.mention}'))
                    return
    @bot.command(name='ports-add-user')
    @is_admin()
    async def ports_add_user(ctx, amount: int, user: discord.Member):
        if amount <= 0:
            await ctx.send(embed=create_error_embed('Invalid Amount', 'Amount must be a positive integer.'))
            return
        else:
            user_id = str(user.id)
            allocate_ports(user_id, amount)
            embed = create_success_embed('Ports Allocated', f'Allocated {amount} port slots to {user.mention}.')
            add_field(embed, 'Quota', f'Total: {get_user_allocation(user_id)} slots', False)
            await ctx.send(embed=embed)
            try:
                dm_embed = create_info_embed('Port Slots Allocated', f'You have been granted {amount} additional port forwarding slots by an admin.\nUse `{PREFIX}ports list` to view your quota and active forwards.')
                await user.send(embed=dm_embed)
            except discord.Forbidden:
                await ctx.send(embed=create_info_embed('DM Failed', f'Could not notify {user.mention} via DM.'))
    @bot.command(name='ports-remove-user')
    @is_admin()
    async def ports_remove_user(ctx, amount: int, user: discord.Member):
        if amount <= 0:
            await ctx.send(embed=create_error_embed('Invalid Amount', 'Amount must be a positive integer.'))
            return
        else:
            user_id = str(user.id)
            current = get_user_allocation(user_id)
            if amount > current:
                amount = current
            deallocate_ports(user_id, amount)
            remaining = get_user_allocation(user_id)
            embed = create_success_embed('Ports Deallocated', f'Removed {amount} port slots from {user.mention}.')
            add_field(embed, 'Remaining Quota', f'{remaining} slots', False)
            await ctx.send(embed=embed)
            try:
                dm_embed = create_warning_embed('Port Slots Reduced', f'Your port forwarding quota has been reduced by {amount} slots by an admin.\nRemaining: {remaining} slots.')
                await user.send(embed=dm_embed)
            except discord.Forbidden:
                await ctx.send(embed=create_info_embed('DM Failed', f'Could not notify {user.mention} via DM.'))
    @bot.command(name='ports-revoke')
    @is_admin()
    async def ports_revoke(ctx, forward_id: int):
        success, user_id = await remove_port_forward(forward_id, is_admin=True)
        if success and user_id:
            try:
                user = await bot.fetch_user(int(user_id))
                dm_embed = create_warning_embed('Port Forward Revoked', f'One of your port forwards (ID: {forward_id}) has been revoked by an admin.')
                await user.send(embed=dm_embed)
            except:
                pass
            await ctx.send(embed=create_success_embed('Revoked', f'Port forward ID {forward_id} revoked.'))
        else:
            await ctx.send(embed=create_error_embed('Failed', 'Port forward ID not found or removal failed.'))
    @bot.command(name='ports')
    async def ports_command(ctx, subcmd: str=None, *args):
        user_id = str(ctx.author.id)
        allocated = get_user_allocation(user_id)
        used = get_user_used_ports(user_id)
        available = allocated - used
        if subcmd is None:
            embed = create_info_embed('Port Forwarding Help', f'**Your Quota:** Allocated: {allocated}, Used: {used}, Available: {available}')
            add_field(embed, 'Commands', f'{PREFIX}ports add <vps_num> <port>\n{PREFIX}ports list\n{PREFIX}ports remove <id>', False)
            await ctx.send(embed=embed)
        else:
            if subcmd == 'add':
                if len(args) < 2:
                    await ctx.send(embed=create_error_embed('Usage', f'Usage: {PREFIX}ports add <vps_number> <vps_port>'))
                else:
                    try:
                        vps_num = int(args[0])
                        vps_port = int(args[1])
                        if vps_port < 1 or vps_port > 65535:
                            raise ValueError
                    except ValueError:
                        await ctx.send(embed=create_error_embed('Invalid Input', 'VPS number and port must be positive integers (port: 1-65535).'))
                        return
                    vps_list = vps_data.get(user_id, [])
                    if vps_num < 1 or vps_num > len(vps_list):
                        await ctx.send(embed=create_error_embed('Invalid VPS', f'Invalid VPS number (1-{len(vps_list)}). Use {PREFIX}myvps to list.'))
                        return
                    else:
                        vps = vps_list[vps_num - 1]
                        container = vps['container_name']
                        node_id = vps['node_id']
                        if used >= allocated:
                            await ctx.send(embed=create_error_embed('Quota Exceeded', f'No available slots. Allocated: {allocated}, Used: {used}. Contact admin for more.'))
                            return
                        else:
                            host_port = await create_port_forward(user_id, container, vps_port, node_id)
                            if host_port:
                                embed = create_success_embed('Port Forward Created', f'VPS #{vps_num} port {vps_port} (TCP/UDP) forwarded to host port {host_port}.')
                                add_field(embed, 'Access', f'External: {YOUR_SERVER_IP}:{host_port} → VPS:{vps_port} (TCP & UDP)', False)
                                add_field(embed, 'Quota Update', f'Used: {used + 1}/{allocated}', False)
                                await ctx.send(embed=embed)
                            else:
                                await ctx.send(embed=create_error_embed('Failed', 'Could not assign host port. Try again later.'))
            else:
                if subcmd == 'list':
                    forwards = get_user_forwards(user_id)
                    embed = create_info_embed('Your Port Forwards', f'**Quota:** Allocated: {allocated}, Used: {used}, Available: {available}')
                    if not forwards:
                        add_field(embed, 'Forwards', 'No active port forwards.', False)
                    else:
                        text = []
                        for f in forwards:
                            vps_num = next((i + 1 for i, v in enumerate(vps_data.get(user_id, [])) if v['container_name'] == f['vps_container']), 'Unknown')
                            created = datetime.fromisoformat(f['created_at']).strftime('%Y-%m-%d %H:%M')
                            created = datetime.fromisoformat(f['created_at']).strftime('%Y-%m-%d %H:%M')
                            text.append(f"**ID {f['id']}** - VPS #{vps_num}: {f['vps_port']} (TCP/UDP) → {f['host_port']} (Created: {created})")
                        add_field(embed, 'Active Forwards', '\n'.join(text[:10]), False)
                        if len(forwards) > 10:
                            add_field(embed, 'Note', f'Showing 10 of {len(forwards)}. Remove unused with {PREFIX}ports remove <id>.')
                    await ctx.send(embed=embed)
                else:
                    if subcmd == 'remove':
                        if len(args) < 1:
                            await ctx.send(embed=create_error_embed('Usage', f'Usage: {PREFIX}ports remove <forward_id>'))
                            return
                        else:
                            try:
                                fid = int(args[0])
                            except ValueError:
                                await ctx.send(embed=create_error_embed('Invalid ID', 'Forward ID must be an integer.'))
                                return
                            success, _ = await remove_port_forward(fid)
                            if success:
                                embed = create_success_embed('Removed', f'Port forward {fid} removed (TCP & UDP).')
                                add_field(embed, 'Quota Update', f'Used: {used - 1}/{allocated}', False)
                                await ctx.send(embed=embed)
                            else:
                                await ctx.send(embed=create_error_embed('Not Found', 'Forward ID not found. Use !ports list.'))
                    else:
                        await ctx.send(embed=create_error_embed('Invalid Subcommand', 'Use: add <vps_num> <port>, list, remove <id>'))
    @bot.command(name='delete-vps')
    @is_admin()
    async def delete_vps(ctx, user: discord.Member, vps_number: int, *, reason: str='No reason'):
        user_id = str(user.id)
        if user_id not in vps_data or vps_number < 1 or vps_number > len(vps_data[user_id]):
            await ctx.send(embed=create_error_embed('Invalid VPS', 'Invalid VPS number or user doesn\'t have that VPS.'))
            return
        else:
            vps = vps_data[user_id][vps_number - 1]
            container_name = vps['container_name']
            node_id = vps.get('node_id', 1)
            await ctx.send(embed=create_info_embed('Deleting VPS', f'Removing VPS #{vps_number} for {user.mention}...'))
            node_result = 'Not checked'
            try:
                await execute_lxc(container_name, f'delete {container_name} --force', node_id=node_id)
                node_result = 'Container deleted successfully.'
            except Exception as e:
                err = str(e).lower()
                if any((x in err for x in ['not found', 'does not exist', 'no such container'])):
                    node_result = 'Container not found (force DB cleanup).'
                else:
                    node_result = f'Container delete failed: {e}'
            conn = get_db()
            cur = conn.cursor()
            cur.execute('DELETE FROM vps WHERE container_name = ?', (container_name,))
            cur.execute('DELETE FROM port_forwards WHERE vps_container = ?', (container_name,))
            conn.commit()
            conn.close()
            del vps_data[user_id][vps_number - 1]
            if not vps_data[user_id]:
                del vps_data[user_id]
                if ctx.guild:
                    role = await get_or_create_vps_role(ctx.guild)
                    if role and role in user.roles:
                            try:
                                await user.remove_roles(role, reason='No VPS ownership')
                            except discord.Forbidden:
                                logger.warning(f'Failed to remove VPS role from {user.name}')
            save_vps_data()
            embed = create_success_embed('🌟 UnixNodes - VPS Deleted Successfully')
            add_field(embed, 'Owner', user.mention, True)
            add_field(embed, 'VPS Number', f'#{vps_number}', True)
            add_field(embed, 'Container', container_name, False)
            add_field(embed, 'Node Result', node_result, False)
            add_field(embed, 'Reason', reason, False)
            await ctx.send(embed=embed)
    @bot.command(name='add-resources')
    @is_admin()
    async def add_resources(ctx, vps_id: str, ram: int=None, cpu: int=None, disk: int=None):
        if ram is None and cpu is None and (disk is None):
            await ctx.send(embed=create_error_embed('Missing Parameters', 'Please specify at least one resource to add (ram, cpu, or disk)'))
            return
        else:
            found_vps = None
            user_id = None
            vps_index = None
            for uid, vps_list in vps_data.items():
                for i, vps in enumerate(vps_list):
                    if vps['container_name'] == vps_id:
                        found_vps = vps
                        user_id = uid
                        vps_index = i
                        break
                if found_vps:
                    break
            if not found_vps:
                await ctx.send(embed=create_error_embed('VPS Not Found', f'No VPS found with ID: `{vps_id}`'))
                return
            else:
                node_id = found_vps['node_id']
                was_running = found_vps.get('status') == 'running' and (not found_vps.get('suspended', False))
                disk_changed = disk is not None
                if was_running:
                    await ctx.send(embed=create_info_embed('Stopping VPS', f'Stopping VPS `{vps_id}` to apply resource changes...'))
                    try:
                        await execute_lxc(vps_id, 'stop {vps_id}', node_id=node_id)
                        found_vps['status'] = 'stopped'
                        save_vps_data()
                    except Exception as e:
                        await ctx.send(embed=create_error_embed('Stop Failed', f'Error stopping VPS: {str(e)}'))
                        return
                changes = []
                try:
                    current_ram_gb = int(found_vps['ram'].replace('GB', ''))
                    current_cpu = int(found_vps['cpu'])
                    current_disk_gb = int(found_vps['storage'].replace('GB', ''))
                    new_ram_gb = current_ram_gb
                    new_cpu = current_cpu
                    new_disk_gb = current_disk_gb
                    if ram is not None and ram > 0:
                            new_ram_gb += ram
                            ram_mb = new_ram_gb * 1024
                            await execute_lxc(vps_id, f'config set {vps_id} limits.memory {ram_mb}MB', node_id=node_id)
                            changes.append(f'RAM: +{ram}GB (New total: {new_ram_gb}GB)')
                    if cpu is not None and cpu > 0:
                            new_cpu += cpu
                            await execute_lxc(vps_id, f'config set {vps_id} limits.cpu {new_cpu}', node_id=node_id)
                            changes.append(f'CPU: +{cpu} cores (New total: {new_cpu} cores)')
                    if disk is not None and disk > 0:
                            new_disk_gb += disk
                            await execute_lxc(vps_id, f'config device set {vps_id} root size={new_disk_gb}GB', node_id=node_id)
                            changes.append(f'Disk: +{disk}GB (New total: {new_disk_gb}GB)')
                    found_vps['ram'] = f'{new_ram_gb}GB'
                    found_vps['cpu'] = str(new_cpu)
                    found_vps['storage'] = f'{new_disk_gb}GB'
                    found_vps['config'] = f'{new_ram_gb}GB RAM / {new_cpu} CPU / {new_disk_gb}GB Disk'
                    vps_data[user_id][vps_index] = found_vps
                    save_vps_data()
                    if was_running:
                        await execute_lxc(vps_id, f'start {vps_id}', node_id=node_id)
                        found_vps['status'] = 'running'
                        save_vps_data()
                        await apply_internal_permissions(vps_id, node_id)
                        await recreate_port_forwards(vps_id)
                    embed = create_success_embed('Resources Added', f'Successfully added resources to VPS `{vps_id}`')
                    add_field(embed, 'Changes Applied', '\n'.join(changes), False)
                    if disk_changed:
                        add_field(embed, 'Disk Note', 'Run `sudo resize2fs /` inside the VPS to expand the filesystem.', False)
                    await ctx.send(embed=embed)
                except Exception as e:
                    await ctx.send(embed=create_error_embed('Resource Addition Failed', f'Error: {str(e)}'))
                    return
    @bot.command(name='status')
    @is_admin()
    async def system_status(ctx):
        """\n    Show complete system status including:\n    - Bot uptime\n    - Total nodes & their status\n    - Running/stopped nodes count\n    - Total RAM/CPU/DISK allocated vs free\n    - Total VPS & users\n    - Running/stopped/suspended VPS counts\n    - Total admin users\n    - Whitelisted VPS\n    """
        start_time = time.time()
        bot_start_time = datetime.now() - datetime.fromtimestamp(start_time - bot.latency)
        bot_uptime = str(bot_start_time).split('.')[0]
        nodes = get_nodes()
        total_nodes = len(nodes)
        running_nodes = 0
        stopped_nodes = 0
        local_nodes = 0
        remote_nodes = 0
        total_node_cpu_allocated = 0
        total_node_ram_allocated = 0
        total_node_disk_allocated = 0
        total_node_cpu_free = 0
        total_node_ram_free = 0
        total_node_disk_free = 0
        total_vps = 0
        total_users = len(vps_data)
        running_vps = 0
        stopped_vps = 0
        suspended_vps = 0
        whitelisted_vps = 0
        total_admins = len(admin_data.get('admins', [])) + 1
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT SUM(allocated_ports) FROM port_allocations')
        total_ports_allocated = cur.fetchone()[0] or 0
        cur.execute('SELECT COUNT(*) FROM port_forwards')
        total_ports_used = cur.fetchone()[0] or 0
        conn.close()
        total_ram_allocated = 0
        total_cpu_allocated = 0
        total_disk_allocated = 0
        for user_id, vps_list in vps_data.items():
            total_vps += len(vps_list)
            for vps in vps_list:
                if vps.get('suspended', False):
                    suspended_vps += 1
                else:
                    if vps.get('status') == 'running':
                        running_vps += 1
                    else:
                        stopped_vps += 1
                if vps.get('whitelisted', False):
                    whitelisted_vps += 1
                try:
                    ram_gb = int(vps['ram'].replace('GB', ''))
                    total_ram_allocated += ram_gb
                except:
                    pass
                try:
                    cpu_cores = int(vps['cpu'])
                    total_cpu_allocated += cpu_cores
                except:
                    pass
                try:
                    disk_gb = int(vps['storage'].replace('GB', ''))
                    total_disk_allocated += disk_gb
                except:
                    pass
                else:
                    pass
        node_statuses = []
        for node in nodes:
            if node['is_local']:
                local_nodes += 1
                node_type = '🖥️ Local'
            else:
                remote_nodes += 1
                node_type = '🌐 Remote'
            if node['is_local']:
                status = '🟢 Online'
                running_nodes += 1
                try:
                    mem_result = subprocess.run(['free', '-m'], capture_output=True, text=True)
                    mem_lines = mem_result.stdout.splitlines()
                    if len(mem_lines) > 1:
                        mem = mem_lines[1].split()
                        total_ram_mb = int(mem[1])
                        used_ram_mb = int(mem[2])
                        free_ram_mb = total_ram_mb - used_ram_mb
                        total_ram_gb = total_ram_mb / 1024
                        free_ram_gb = free_ram_mb / 1024
                    else:
                        total_ram_gb = 0
                        free_ram_gb = 0
                    cpu_result = subprocess.run(['nproc'], capture_output=True, text=True)
                    total_cpu = int(cpu_result.stdout.strip()) if cpu_result.stdout.strip() else 0
                    disk_result = subprocess.run(['df', '-h', '/'], capture_output=True, text=True)
                    disk_lines = disk_result.stdout.splitlines()
                    if len(disk_lines) > 1:
                        disk_parts = disk_lines[1].split()
                        total_disk_str = disk_parts[1]
                        if 'T' in total_disk_str:
                            total_disk = float(total_disk_str.replace('T', '')) * 1024
                        else:
                            if 'G' in total_disk_str:
                                total_disk = float(total_disk_str.replace('G', ''))
                            else:
                                if 'M' in total_disk_str:
                                    total_disk = float(total_disk_str.replace('M', '')) / 1024
                                else:
                                    total_disk = 0
                    else:
                        total_disk = 0
                    free_cpu = max(0, total_cpu - total_cpu_allocated // total_nodes)
                    free_disk = max(0, total_disk - total_disk_allocated // total_nodes)
                    total_node_ram_allocated += total_ram_gb - free_ram_gb
                    total_node_cpu_allocated += total_cpu - free_cpu
                    total_node_disk_allocated += total_disk - free_disk
                    total_node_ram_free += free_ram_gb
                    total_node_cpu_free += free_cpu
                    total_node_disk_free += free_disk
                except Exception as e:
                    logger.error(f'Error getting local node resources: {e}')
                    status = '⚠️ Unknown'
                    total_node_ram_free = 0
                    total_node_cpu_free = 0
                    total_node_disk_free = 0
                else:
                    pass
            else:
                try:
                    response = requests.get(f"{node['url']}/api/ping", params={'api_key': node['api_key']}, timeout=5)
                    if response.status_code == 200:
                        status = '🟢 Online'
                        running_nodes += 1
                    else:
                        status = '🔴 Offline'
                        stopped_nodes += 1
                except:
                    status = '🔴 Offline'
                    stopped_nodes += 1
            node_vps_count = get_current_vps_count(node['id'])
            capacity = node['total_vps']
            usage_percentage = node_vps_count / capacity * 100 if capacity > 0 else 0
            node_statuses.append(f"**{node['name']}** ({node_type})\n📍 {node['location']} • 📊 {node_vps_count}/{capacity} VPS ({usage_percentage:.0f}%)\nStatus: {status}")
        response_time = (time.time() - start_time) * 1000
        embed = create_embed(title='📊 System Status Dashboard', description=f'**{BOT_NAME}** - Complete System Overview\n*Generated in {response_time:.0f}ms*', color=1710618)
        add_field(embed, '🤖 Bot Status', f'**Uptime:** {bot_uptime}\n**Latency:** {round(bot.latency * 1000)}ms\n**Version:** {BOT_VERSION}\n**Developer:** {BOT_DEVELOPER}', True)
        add_field(embed, '🌐 Nodes Overview', f'**Total Nodes:** {total_nodes}\n**Running:** {running_nodes} 🟢\n**Stopped:** {stopped_nodes} 🔴\n**Local/Remote:** {local_nodes}/{remote_nodes}', True)
        add_field(embed, '👥 Users & VPS', f'**Total Users:** {total_users}\n**Total VPS:** {total_vps}\n**Running:** {running_vps} 🟢\n**Stopped:** {stopped_vps} 🔴\n**Suspended:** {suspended_vps} 🟡\n**Whitelisted:** {whitelisted_vps} ✅', True)
        add_field(embed, '💾 Resource Allocation', f'**RAM Allocated:** {total_ram_allocated} GB\n**RAM Free:** {total_node_ram_free:.1f} GB\n**CPU Allocated:** {total_cpu_allocated} Cores\n**CPU Free:** {total_node_cpu_free:.1f} Cores\n**Disk Allocated:** {total_disk_allocated} GB\n**Disk Free:** {total_node_disk_free:.1f} GB', True)
        add_field(embed, '⚙️ System Information', f'**Total Admins:** {total_admins}\n**Main Admin:** <@{MAIN_ADMIN_ID}>\n**Ports Allocated:** {total_ports_allocated}\n**Ports In Use:** {total_ports_used}\n**Ports Available:** {total_ports_allocated - total_ports_used}', True)
        if node_statuses:
            node_text = '\n\n'.join(node_statuses)
            chunks = [node_text[i:i + 1024] for i in range(0, len(node_text), 1024)]
            for idx, chunk in enumerate(chunks, 1):
                title = '📡 Node Details' if idx == 1 else f'📡 Node Details (Part {idx})'
                add_field(embed, title, chunk, False)
        health_status = '✅ Excellent'
        health_color = 65416
        if running_nodes == 0:
            health_status = '🔴 Critical - No nodes running'
            health_color = 16724838
        else:
            if stopped_nodes > 0:
                health_status = '🟡 Warning - Some nodes offline'
                health_color = 16755200
            else:
                if total_vps == 0:
                    health_status = 'ℹ️ No VPS deployed'
                    health_color = 52479
        add_field(embed, '🏥 System Health', health_status, False)
        embed.set_footer(text=f"{BOT_NAME} System Status • Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", icon_url='https://i.imgur.com/dpatuSj.png')
        await ctx.send(embed=embed)
    @bot.command(name='status-summary')
    @is_admin()
    async def status_summary(ctx):
        """\n    Quick summary of system status\n    """
        nodes = get_nodes()
        total_nodes = len(nodes)
        running_nodes = 0
        for node in nodes:
            if node['is_local']:
                running_nodes += 1
                continue
            else:
                try:
                    response = requests.get(f"{node['url']}/api/ping", params={'api_key': node['api_key']}, timeout=3)
                    if response.status_code == 200:
                        running_nodes += 1
                except:
                    pass
                else:
                    pass
        total_vps = sum((len(vps_list) for vps_list in vps_data.values()))
        total_users = len(vps_data)
        running_vps = 0
        stopped_vps = 0
        suspended_vps = 0
        for vps_list in vps_data.values():
            for vps in vps_list:
                if vps.get('suspended', False):
                    suspended_vps += 1
                else:
                    if vps.get('status') == 'running':
                        running_vps += 1
                    else:
                        stopped_vps += 1
        embed = create_success_embed('📈 Quick Status Summary', f'**Nodes:** {running_nodes}/{total_nodes} 🟢\n**VPS:** {total_vps} total\n• Running: {running_vps} 🟢\n• Stopped: {stopped_vps} 🔴\n• Suspended: {suspended_vps} 🟡\n**Users:** {total_users} 👥\n**Bot Latency:** {round(bot.latency * 1000)}ms')
        embed.set_footer(text=f'Use \'{PREFIX}status\' for detailed information')
        await ctx.send(embed=embed)
    @bot.command(name='admin-add')
    @is_main_admin()
    async def admin_add(ctx, user: discord.Member):
        user_id = str(user.id)
        if user_id == str(MAIN_ADMIN_ID):
            await ctx.send(embed=create_error_embed('Already Admin', 'This user is already the main admin!'))
            return
        else:
            if user_id in admin_data.get('admins', []):
                await ctx.send(embed=create_error_embed('Already Admin', f'{user.mention} is already an admin!'))
            else:
                admin_data['admins'].append(user_id)
                save_admin_data()
                await ctx.send(embed=create_success_embed('Admin Added', f'{user.mention} is now an admin!'))
                try:
                    await user.send(embed=create_embed('🎉 Admin Role Granted', f'You are now an admin by {ctx.author.mention}', 65416))
                except discord.Forbidden:
                    await ctx.send(embed=create_info_embed('Notification Failed', f'Could not DM {user.mention}'))
    @bot.command(name='admin-remove')
    @is_main_admin()
    async def admin_remove(ctx, user: discord.Member):
        user_id = str(user.id)
        if user_id == str(MAIN_ADMIN_ID):
            await ctx.send(embed=create_error_embed('Cannot Remove', 'You cannot remove the main admin!'))
            return
        else:
            if user_id not in admin_data.get('admins', []):
                await ctx.send(embed=create_error_embed('Not Admin', f'{user.mention} is not an admin!'))
                return
            else:
                admin_data['admins'].remove(user_id)
                save_admin_data()
                await ctx.send(embed=create_success_embed('Admin Removed', f'{user.mention} is no longer an admin!'))
                try:
                    await user.send(embed=create_embed('⚠️ Admin Role Revoked', f'Your admin role was removed by {ctx.author.mention}', 16724838))
                except discord.Forbidden:
                    await ctx.send(embed=create_info_embed('Notification Failed', f'Could not DM {user.mention}'))
    @bot.command(name='admin-list')
    @is_main_admin()
    async def admin_list(ctx):
        admins = admin_data.get('admins', [])
        main_admin = await bot.fetch_user(MAIN_ADMIN_ID)
        embed = create_embed('👑 Admin Team', 'Current administrators:', 1710618)
        add_field(embed, '🔰 Main Admin', f'{main_admin.mention} (ID: {MAIN_ADMIN_ID})', False)
        if admins:
            admin_list = []
            for admin_id in admins:
                try:
                    admin_user = await bot.fetch_user(int(admin_id))
                    admin_list.append(f'• {admin_user.mention} (ID: {admin_id})')
                except:
                    admin_list.append(f'• Unknown User (ID: {admin_id})')
                else:
                    pass
            admin_text = '\n'.join(admin_list)
            add_field(embed, '🛡️ Admins', admin_text, False)
        else:
            add_field(embed, '🛡️ Admins', 'No additional admins', False)
        await ctx.send(embed=embed)
    @bot.command(name='userinfo')
    @is_admin()
    async def user_info(ctx, user: discord.Member):
        user_id = str(user.id)
        vps_list = vps_data.get(user_id, [])
        embed = create_embed(title='👤 User Dashboard', description=f'Statistics & resources for {user.mention}', color=1710618)
        embed.add_field(name='👤 User', value=f"**Name:** `{user.name}`\n**ID:** `{user.id}`\n**Joined:** `{(user.joined_at.strftime('%Y-%m-%d') if user.joined_at else 'Unknown')}`", inline=True)
        is_admin_user = user_id == str(MAIN_ADMIN_ID) or user_id in admin_data.get('admins', [])
        embed.add_field(name='🛡️ Admin', value='✅ Yes' if is_admin_user else '❌ No', inline=True)
        embed.add_field(name='🖥️ VPS Count', value=f'`{len(vps_list)}` VPS', inline=True)
        if vps_list:
            total_ram = total_cpu = total_storage = 0
            running = suspended = whitelisted = 0
            vps_lines = []
            for i, vps in enumerate(vps_list, start=1):
                node = get_node(vps.get('node_id'))
                node_name = node['name'] if node else 'Unknown'
                ram = int(vps.get('ram', '0GB').replace('GB', ''))
                storage = int(vps.get('storage', '0GB').replace('GB', ''))
                cpu = int(vps.get('cpu', 0))
                total_ram += ram
                total_storage += storage
                total_cpu += cpu
                if vps.get('suspended'):
                    status = '⛔ SUSPENDED'
                    suspended += 1
                else:
                    if vps.get('status') == 'running':
                        status = '🟢 RUNNING'
                        running += 1
                    else:
                        status = '🔴 STOPPED'
                if vps.get('whitelisted'):
                    whitelisted += 1
                vps_lines.append(f"**{i}.** `{vps['container_name']}`\n{status} | `{ram}GB` RAM • `{cpu}` CPU • `{storage}GB` Disk\n📍 Node: `{node_name}`")
            embed.add_field(name='📊 VPS Summary', value=f'🖥️ `{len(vps_list)}` Total\n🟢 `{running}` Running\n⛔ `{suspended}` Suspended\n✅ `{whitelisted}` Whitelisted', inline=True)
            embed.add_field(name='📈 Resources', value=f'**RAM:** `{total_ram} GB`\n**CPU:** `{total_cpu} Cores`\n**Disk:** `{total_storage} GB`', inline=True)
            port_quota = get_user_allocation(user_id)
            port_used = get_user_used_ports(user_id)
            embed.add_field(name='🌐 Ports', value=f'`{port_used}/{port_quota}` Used', inline=True)
            vps_text = '\n\n'.join(vps_lines)
            for i in range(0, len(vps_text), 1024):
                embed.add_field(name='📋 VPS List', value=vps_text[i:i + 1024], inline=False)
        else:
            embed.add_field(name='🖥️ VPS', value='❌ No VPS assigned', inline=False)
        embed.set_footer(text='UnixNodes • User Resource Dashboard')
        embed.timestamp = ctx.message.created_at
        await ctx.send(embed=embed)
    @bot.command(name='serverstats')
    @is_admin()
    async def server_stats(ctx):
        total_users = len(vps_data)
        total_admins = len(admin_data.get('admins', [])) + 1
        total_vps = sum((len(vps_list) for vps_list in vps_data.values()))
        total_ram = total_cpu = total_storage = 0
        running_vps = suspended_vps = stopped_vps = 0
        whitelisted_vps = 0
        for vps_list in vps_data.values():
            for vps in vps_list:
                total_ram += int(vps.get('ram', '0GB').replace('GB', ''))
                total_storage += int(vps.get('storage', '0GB').replace('GB', ''))
                total_cpu += int(vps.get('cpu', 0))
                if vps.get('status') == 'running':
                    if vps.get('suspended', False):
                        suspended_vps += 1
                    else:
                        running_vps += 1
                else:
                    stopped_vps += 1
                if vps.get('whitelisted', False):
                    whitelisted_vps += 1
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT SUM(allocated_ports) FROM port_allocations')
        total_ports_allocated = cur.fetchone()[0] or 0
        cur.execute('SELECT COUNT(*) FROM port_forwards')
        total_ports_used = cur.fetchone()[0] or 0
        conn.close()
        embed = create_embed(title='📊 Server Statistics', description='**Live Infrastructure Dashboard**', color=1710618)
        embed.add_field(name='👥 Users', value=f'`{total_users}` Users\n`{total_admins}` Admins', inline=True)
        embed.add_field(name='🖥️ VPS', value=f'Total: `{total_vps}`\n🟢 `{running_vps}` Running\n⛔ `{suspended_vps}` Suspended', inline=True)
        embed.add_field(name='📌 Status', value=f'🔴 `{stopped_vps}` Stopped\n✅ `{whitelisted_vps}` Whitelisted', inline=True)
        embed.add_field(name='📈 RAM', value=f'`{total_ram} GB`', inline=True)
        embed.add_field(name='⚙️ CPU', value=f'`{total_cpu} Cores`', inline=True)
        embed.add_field(name='💾 Storage', value=f'`{total_storage} GB`', inline=True)
        embed.add_field(name='🌐 Ports Allocated', value=f'`{total_ports_allocated}`', inline=True)
        embed.add_field(name='🔌 Ports In Use', value=f'`{total_ports_used}`', inline=True)
        embed.add_field(name='📊 Utilization', value=f'`{total_ports_used}/{total_ports_allocated}`' if total_ports_allocated else '`N/A`', inline=True)
        embed.set_footer(text='UnixNodes • Real-Time Monitoring')
        embed.timestamp = ctx.message.created_at
        await ctx.send(embed=embed)
    @bot.command(name='vpsinfo')
    @is_admin()
    async def vps_info(ctx, container_name: str=None):
        if not container_name:
            all_vps = []
            for user_id, vps_list in vps_data.items():
                try:
                    user = await bot.fetch_user(int(user_id))
                    for i, vps in enumerate(vps_list):
                        node = get_node(vps['node_id'])
                        node_name = node['name'] if node else 'Unknown'
                        status_text = vps.get('status', 'unknown').upper()
                        if vps.get('suspended', False):
                            status_text += ' (SUSPENDED)'
                        if vps.get('whitelisted', False):
                            status_text += ' (WHITELISTED)'
                        all_vps.append(f"**{user.name}** - VPS {i + 1}: `{vps['container_name']}` - {status_text} (Node: {node_name})")
                except:
                    pass
                else:
                    pass
            vps_text = '\n'.join(all_vps)
            chunks = [vps_text[i:i + 1024] for i in range(0, len(vps_text), 1024)]
            for idx, chunk in enumerate(chunks, 1):
                embed = create_embed(f'🖥️ All VPS (Part {idx})', 'List of all VPS deployments', 1710618)
                add_field(embed, 'VPS List', chunk, False)
                await ctx.send(embed=embed)
            return
        else:
            found_vps = None
            found_user = None
            for user_id, vps_list in vps_data.items():
                for vps in vps_list:
                    if vps['container_name'] == container_name:
                        found_vps = vps
                        found_user = await bot.fetch_user(int(user_id))
                        break
                if found_vps:
                    break
            if not found_vps:
                await ctx.send(embed=create_error_embed('VPS Not Found', f'No VPS found with container name: `{container_name}`'))
                return
            else:
                node = get_node(found_vps['node_id'])
                node_name = node['name'] if node else 'Unknown'
                suspended_text = ' (SUSPENDED)' if found_vps.get('suspended', False) else ''
                whitelisted_text = ' (WHITELISTED)' if found_vps.get('whitelisted', False) else ''
                embed = create_embed(f'🖥️ VPS Information - {container_name}', f'Details for VPS owned by {found_user.mention}{suspended_text}{whitelisted_text} on node {node_name}', 1710618)
                add_field(embed, '👤 Owner', f'**Name:** {found_user.name}\n**ID:** {found_user.id}', False)
                add_field(embed, '📊 Specifications', f"**RAM:** {found_vps['ram']}\n**CPU:** {found_vps['cpu']} Cores\n**Storage:** {found_vps['storage']}", False)
                add_field(embed, '📈 Status', f"**Current:** {found_vps.get('status', 'unknown').upper()}{suspended_text}{whitelisted_text}\n**Suspended:** {found_vps.get('suspended', False)}\n**Whitelisted:** {found_vps.get('whitelisted', False)}\n**Created:** {found_vps.get('created_at', 'Unknown')}", False)
                if 'config' in found_vps:
                    add_field(embed, '⚙️ Configuration', f"**Config:** {found_vps['config']}", False)
                if found_vps.get('shared_with'):
                    shared_users = []
                    for shared_id in found_vps['shared_with']:
                        try:
                            shared_user = await bot.fetch_user(int(shared_id))
                            shared_users.append(f'• {shared_user.mention}')
                        except:
                            shared_users.append(f'• Unknown User ({shared_id})')
                        else:
                            pass
                    shared_text = '\n'.join(shared_users)
                    add_field(embed, '🔗 Shared With', shared_text, False)
                conn = get_db()
                cur = conn.cursor()
                cur.execute('SELECT COUNT(*) FROM port_forwards WHERE vps_container = ?', (container_name,))
                port_count = cur.fetchone()[0]
                conn.close()
                add_field(embed, '🌐 Active Ports', f'{port_count} forwarded ports (TCP/UDP)', False)
                await ctx.send(embed=embed)
    @bot.command(name='restart-vps')
    @is_admin()
    async def restart_vps(ctx, container_name: str):
        node_id = find_node_id_for_container(container_name)
        await ctx.send(embed=create_info_embed('Restarting VPS', f'Restarting VPS `{container_name}`...'))
        try:
            await execute_lxc(container_name, f'restart {container_name}', node_id=node_id)
            for user_id, vps_list in vps_data.items():
                for vps in vps_list:
                    if vps['container_name'] == container_name:
                        vps['status'] = 'running'
                        save_vps_data()
                        break
            await apply_internal_permissions(container_name, node_id)
            await recreate_port_forwards(container_name)
            await ctx.send(embed=create_success_embed('VPS Restarted', f'VPS `{container_name}` has been restarted successfully!'))
        except Exception as e:
            await ctx.send(embed=create_error_embed('Restart Failed', f'Error: {str(e)}'))
    @bot.command(name='exec')
    @is_admin()
    async def execute_command(ctx, container_name: str, *, command: str):
        node_id = find_node_id_for_container(container_name)
        await ctx.send(embed=create_info_embed('Executing Command', f'Running command in VPS `{container_name}`...'))
        try:
            output = await execute_lxc(container_name, f'exec {container_name} -- bash -c \"{command}\"', node_id=node_id)
            embed = create_embed(f'Command Output - {container_name}', f'Command: `{command}`', 1710618)
            if output.strip():
                if len(output) > 1000:
                    output = output[:1000] + '\n... (truncated)'
                add_field(embed, '📤 Output', f'```\n{output}\n```', False)
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=create_error_embed('Execution Failed', f'Error: {str(e)}'))
    @bot.command(name='stop-vps-all')
    @is_admin()
    async def stop_all_vps(ctx):
        embed = create_warning_embed('Stopping All VPS', '⚠️ **WARNING:** This will stop ALL running VPS on all nodes.\n\nThis action cannot be undone. Continue?')
        class ConfirmView(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=60)
            @discord.ui.button(label='Stop All VPS', style=discord.ButtonStyle.danger)
            async def confirm(self, interaction: discord.Interaction, item: discord.ui.Button):
                await interaction.response.defer()
                try:
                    stopped_count = 0
                    nodes = get_nodes()
                    for node in nodes:
                        if node['is_local']:
                            proc = await asyncio.create_subprocess_exec('lxc', 'stop', '--all', '--force', stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                            stdout, stderr = await proc.communicate()
                            if proc.returncode!= 0:
                                logger.error(f'Failed to stop all on local node: {stderr.decode()}')
                                continue
                        else:
                            url = f"{node['url']}/api/execute"
                            data = {'command': 'lxc stop --all --force'}
                            params = {'api_key': node['api_key']}
                            response = requests.post(url, json=data, params=params)
                            if response.status_code!= 200:
                                logger.error(f"Failed to stop all on node {node['name']}")
                                continue
                        for user_id, vps_list in vps_data.items():
                            for vps in vps_list:
                                if vps.get('node_id') == node['id'] and vps.get('status') == 'running':
                                        vps['status'] = 'stopped'
                                        vps['suspended'] = False
                                        stopped_count += 1
                    save_vps_data()
                    embed = create_success_embed('All VPS Stopped', f'Successfully stopped {stopped_count} VPS across all nodes.')
                    await interaction.followup.send(embed=embed)
                except Exception as e:
                    embed = create_error_embed('Error', f'Error stopping VPS: {str(e)}')
                    await interaction.followup.send(embed=embed)
                    return
            @discord.ui.button(label='Cancel', style=discord.ButtonStyle.secondary)
            async def cancel(self, interaction: discord.Interaction, item: discord.ui.Button):
                await interaction.response.edit_message(embed=create_info_embed('Operation Cancelled', 'The stop all VPS operation has been cancelled.'))
        await ctx.send(embed=embed, view=ConfirmView())
    @bot.command(name='cpu-monitor')
    @is_admin()
    async def resource_monitor_control(ctx, action: str='status'):
        global resource_monitor_active
        if action.lower() == 'status':
            status = 'Active' if resource_monitor_active else 'Inactive'
            embed = create_embed('Resource Monitor Status', f'Resource monitoring is currently **{status}** (logs only; no auto-stop)', 52479 if resource_monitor_active else 16755200)
            add_field(embed, 'Thresholds', f'{CPU_THRESHOLD}% CPU / {RAM_THRESHOLD}% RAM usage', True)
            add_field(embed, 'Check Interval', '60 seconds (all nodes)', True)
            await ctx.send(embed=embed)
        else:
            if action.lower() == 'enable':
                resource_monitor_active = True
                await ctx.send(embed=create_success_embed('Resource Monitor Enabled', 'Resource monitoring has been enabled.'))
            else:
                if action.lower() == 'disable':
                    resource_monitor_active = False
                    await ctx.send(embed=create_warning_embed('Resource Monitor Disabled', 'Resource monitoring has been disabled.'))
                else:
                    await ctx.send(embed=create_error_embed('Invalid Action', f'Use: `{PREFIX}cpu-monitor <status|enable|disable>`'))
    @bot.command(name='resize-vps')
    @is_admin()
    async def resize_vps(ctx, container_name: str, ram: int=None, cpu: int=None, disk: int=None):
        if ram is None and cpu is None and (disk is None):
            await ctx.send(embed=create_error_embed('Missing Parameters', 'Please specify at least one resource to resize (ram, cpu, or disk)'))
            return
        else:
            found_vps = None
            user_id = None
            vps_index = None
            for uid, vps_list in vps_data.items():
                for i, vps in enumerate(vps_list):
                    if vps['container_name'] == container_name:
                        found_vps = vps
                        user_id = uid
                        vps_index = i
                        break
                if found_vps:
                    break
            if not found_vps:
                await ctx.send(embed=create_error_embed('VPS Not Found', f'No VPS found with container name: `{container_name}`'))
                return
            else:
                node_id = found_vps['node_id']
                was_running = found_vps.get('status') == 'running' and (not found_vps.get('suspended', False))
                disk_changed = disk is not None
                if was_running:
                    await ctx.send(embed=create_info_embed('Stopping VPS', f'Stopping VPS `{container_name}` to apply resource changes...'))
                    try:
                        await execute_lxc(container_name, f'stop {container_name}', node_id=node_id)
                        found_vps['status'] = 'stopped'
                        save_vps_data()
                    except Exception as e:
                        await ctx.send(embed=create_error_embed('Stop Failed', f'Error stopping VPS: {str(e)}'))
                changes = []
                try:
                    new_ram = int(found_vps['ram'].replace('GB', ''))
                    new_cpu = int(found_vps['cpu'])
                    new_disk = int(found_vps['storage'].replace('GB', ''))
                    if ram is not None and ram > 0:
                            new_ram = ram
                            ram_mb = ram * 1024
                            await execute_lxc(container_name, f'config set {container_name} limits.memory {ram_mb}MB', node_id=node_id)
                            changes.append(f'RAM: {ram}GB')
                    if cpu is not None and cpu > 0:
                            new_cpu = cpu
                            await execute_lxc(container_name, f'config set {container_name} limits.cpu {cpu}', node_id=node_id)
                            changes.append(f'CPU: {cpu} cores')
                    if disk is not None and disk > 0:
                            new_disk = disk
                            await execute_lxc(container_name, f'config device set {container_name} root size={disk}GB', node_id=node_id)
                            changes.append(f'Disk: {disk}GB')
                    found_vps['ram'] = f'{new_ram}GB'
                    found_vps['cpu'] = str(new_cpu)
                    found_vps['storage'] = f'{new_disk}GB'
                    found_vps['config'] = f'{new_ram}GB RAM / {new_cpu} CPU / {new_disk}GB Disk'
                    vps_data[user_id][vps_index] = found_vps
                    save_vps_data()
                    if was_running:
                        await execute_lxc(container_name, f'start {container_name}', node_id=node_id)
                        found_vps['status'] = 'running'
                        save_vps_data()
                        await apply_internal_permissions(container_name, node_id)
                        await recreate_port_forwards(container_name)
                    embed = create_success_embed('VPS Resized', f'Successfully resized resources for VPS `{container_name}`')
                    add_field(embed, 'Changes Applied', '\n'.join(changes), False)
                    if disk_changed:
                        add_field(embed, 'Disk Note', 'Run `sudo resize2fs /` inside the VPS to expand the filesystem.', False)
                    await ctx.send(embed=embed)
                except Exception as e:
                    await ctx.send(embed=create_error_embed('Resize Failed', f'Error: {str(e)}'))
                    return
    @bot.command(name='clone-vps')
    @is_admin()
    async def clone_vps(ctx, container_name: str, new_name: str=None):
        # irreducible cflow, using cdg fallback
        if not new_name:
            timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
            new_name = f'{BOT_NAME.lower()}-{container_name}-clone-{timestamp}'
        node_id = find_node_id_for_container(container_name)
        await ctx.send(embed=create_info_embed('Cloning VPS', f'Cloning VPS `{container_name}` to `{new_name}`...'))
            found_vps = None
            user_id = None
            for uid, vps_list in vps_data.items():
                for vps in vps_list:
                    if vps['container_name'] == container_name:
                        found_vps = vps
                        user_id = uid
                        break
                if found_vps:
                    break
            if not found_vps:
                await ctx.send(embed=create_error_embed('VPS Not Found', f'No VPS found with container name: `{container_name}`'))
                    return
                await execute_lxc(container_name, f'copy {container_name} {new_name}', node_id=node_id)
                await apply_lxc_config(new_name, node_id)
                await execute_lxc(new_name, f'start {new_name}', node_id=node_id)
                await apply_internal_permissions(new_name, node_id)
                await recreate_port_forwards(new_name)
                if user_id not in vps_data:
                    vps_data[user_id] = []
                new_vps = found_vps.copy()
                new_vps['container_name'] = new_name
                new_vps['status'] = 'running'
                new_vps['suspended'] = False
                new_vps['whitelisted'] = False
                new_vps['suspension_history'] = []
                new_vps['created_at'] = datetime.now().isoformat()
                new_vps['shared_with'] = []
                new_vps['id'] = None
                vps_data[user_id].append(new_vps)
                save_vps_data()
                embed = create_success_embed('VPS Cloned', f'Successfully cloned VPS `{container_name}` to `{new_name}`')
                add_field(embed, 'New VPS Details', f"**RAM:** {new_vps['ram']}\n**CPU:** {new_vps['cpu']} Cores\n**Storage:** {new_vps['storage']}", False)
                add_field(embed, 'Features', 'Nesting, Privileged, FUSE, Kernel Modules (Docker Ready), Unprivileged Ports from 0', False)
                await ctx.send(embed=embed)
                except Exception as e:
                        await ctx.send(embed=create_error_embed('Clone Failed', f'Error: {str(e)}'))
                            return
    @bot.command(name='migrate-vps')
    @is_admin()
    async def migrate_vps(ctx, container_name: str, target_node_id: int):
        node_id = find_node_id_for_container(container_name)
        target_node = get_node(target_node_id)
        if not target_node:
            await ctx.send(embed=create_error_embed('Invalid Node', 'Target node not found.'))
            return
        else:
            await ctx.send(embed=create_info_embed('Migrating VPS', f"Migrating VPS `{container_name}` to node {target_node['name']}..."))
            try:
                await execute_lxc(container_name, f'stop {container_name}', node_id=node_id)
                temp_name = f'{BOT_NAME.lower()}-{container_name}-temp-{int(time.time())}'
                await execute_lxc(container_name, f'copy {container_name} {temp_name} -s {DEFAULT_STORAGE_POOL}', node_id=target_node_id)
                await execute_lxc(container_name, f'delete {container_name} --force', node_id=node_id)
                await execute_lxc(temp_name, f'rename {temp_name} {container_name}', node_id=target_node_id)
                await apply_lxc_config(container_name, target_node_id)
                await execute_lxc(container_name, f'start {container_name}', node_id=target_node_id)
                await apply_internal_permissions(container_name, target_node_id)
                await recreate_port_forwards(container_name)
                for user_id, vps_list in vps_data.items():
                    for vps in vps_list:
                        if vps['container_name'] == container_name:
                            vps['node_id'] = target_node_id
                            vps['status'] = 'running'
                            vps['suspended'] = False
                            save_vps_data()
                            break
                await ctx.send(embed=create_success_embed('VPS Migrated', f"Successfully migrated VPS `{container_name}` to node {target_node['name']}"))
            except Exception as e:
                await ctx.send(embed=create_error_embed('Migration Failed', f'Error: {str(e)}'))
    @bot.command(name='vps-stats')
    @is_admin()
    async def vps_stats(ctx, container_name: str):
        node_id = find_node_id_for_container(container_name)
        await ctx.send(embed=create_info_embed('Gathering Statistics', f'Collecting statistics for VPS `{container_name}`...'))
        try:
            stats = await get_container_stats(container_name, node_id)
            embed = create_embed(f'📊 VPS Statistics - {container_name}', 'Resource usage statistics', 1710618)
            add_field(embed, '📈 Status', f"**{stats['status'].upper()}**", False)
            add_field(embed, '💻 CPU Usage', f"**{stats['cpu']:.1f}%**", True)
            add_field(embed, '🧠 Memory Usage', f"**{stats['ram']['used']}/{stats['ram']['total']} MB ({stats['ram']['pct']:.1f}%)**", True)
            add_field(embed, '💾 Disk Usage', f"**{stats['disk']}**", True)
            add_field(embed, '⏱️ Uptime', f"**{stats['uptime']}**", True)
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=create_error_embed('Statistics Failed', f'Error: {str(e)}'))
    @bot.command(name='node-check')
    @is_admin()
    async def node_check(ctx, node_id: int):
        """Check node status and available storage pools"""
        node = get_node(node_id)
        if not node:
            await ctx.send(embed=create_error_embed('Node Not Found', f'Node ID {node_id} not found.'))
            return
        else:
            embed = create_info_embed(f"Node Check - {node['name']}", f"Checking status and configuration of node {node['name']}...")
            status = await get_node_status(node_id)
            add_field(embed, '📡 Connection Status', status, False)
            if status.startswith('🟢'):
                try:
                    pools_output = await execute_lxc('', 'storage list', node_id=node_id, timeout=30)
                    add_field(embed, '💾 Available Storage Pools', f'```{pools_output}```', False)
                    try:
                        profile_output = await execute_lxc('', 'profile list', node_id=node_id, timeout=30)
                        add_field(embed, '📋 Available Profiles', f'```{profile_output[:500]}...```', False)
                    except Exception as e:
                        add_field(embed, '📋 Profiles', f'Error: {str(e)[:200]}', False)
                except Exception as e:
                    add_field(embed, '💾 Storage Pools', f'Error: {str(e)[:200]}', False)
                try:
                    test_response = requests.get(f"{node['url']}/api/ping", params={'api_key': node['api_key']}, timeout=5)
                    add_field(embed, '🔌 API Endpoint', f"✅ Reachable\nURL: {node['url']}", False)
                except Exception as e:
                    add_field(embed, '🔌 API Endpoint', f'❌ Unreachable\nError: {str(e)[:200]}', False)
                else:
                    pass
            else:
                add_field(embed, '⚠️ Status', 'Node is offline or unreachable', False)
            await ctx.send(embed=embed)
    @bot.command(name='vps-network')
    @is_admin()
    async def vps_network(ctx, container_name: str, action: str, value: str=None):
        # irreducible cflow, using cdg fallback
        node_id = find_node_id_for_container(container_name)
        if action.lower() not in ['list', 'add', 'remove', 'limit']:
            await ctx.send(embed=create_error_embed('Invalid Action', f'Use: `{PREFIX}vps-network <container> <list|add|remove|limit> [value]`'))
            if action.lower() == 'list':
                output = await execute_lxc(container_name, f'exec {container_name} -- ip addr', node_id=node_id)
                if len(output) > 1000:
                    output = output[:1000] + '\n... (truncated)'
                embed = create_embed(f'🌐 Network Interfaces - {container_name}', 'Network configuration', 1710618)
                add_field(embed, 'Interfaces', f'```\n{output}\n```', False)
                await ctx.send(embed=embed)
                if action.lower() == 'limit' and value:
                    await execute_lxc(container_name, f'config device set {container_name} eth0 limits.egress {value}', node_id=node_id)
                    await execute_lxc(container_name, f'config device set {container_name} eth0 limits.ingress {value}', node_id=node_id)
                    await ctx.send(embed=create_success_embed('Network Limited', f'Set network limit to {value} for `{container_name}`'))
                    if action.lower() == 'add' and value:
                        await execute_lxc(container_name, f'config device add {container_name} eth1 nic nictype=bridged parent={value}', node_id=node_id)
                        await ctx.send(embed=create_success_embed('Network Added', f'Added network interface to VPS `{container_name}` with bridge `{value}`'))
                            return
                        if action.lower() == 'remove' and value:
                            await execute_lxc(container_name, f'config device remove {container_name} {value}', node_id=node_id)
                            await ctx.send(embed=create_success_embed('Network Removed', f'Removed network interface `{value}` from VPS `{container_name}`'))
                                return
                            await ctx.send(embed=create_error_embed('Invalid Parameters', 'Please provide valid parameters for the action'))
                except Exception as e:
                        await ctx.send(embed=create_error_embed('Network Management Failed', f'Error: {str(e)}'))
                            return
    @bot.command(name='vps-processes')
    @is_admin()
    async def vps_processes(ctx, container_name: str):
        node_id = find_node_id_for_container(container_name)
        await ctx.send(embed=create_info_embed('Gathering Processes', f'Listing processes in VPS `{container_name}`...'))
        try:
            output = await execute_lxc(container_name, f'exec {container_name} -- ps aux', node_id=node_id)
            if len(output) > 1000:
                output = output[:1000] + '\n... (truncated)'
            embed = create_embed(f'⚙️ Processes - {container_name}', 'Running processes', 1710618)
            add_field(embed, 'Process List', f'```\n{output}\n```', False)
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=create_error_embed('Process Listing Failed', f'Error: {str(e)}'))
            return
    @bot.command(name='vps-logs')
    @is_admin()
    async def vps_logs(ctx, container_name: str, lines: int=50):
        node_id = find_node_id_for_container(container_name)
        await ctx.send(embed=create_info_embed('Gathering Logs', f'Fetching last {lines} lines from VPS `{container_name}`...'))
        try:
            output = await execute_lxc(container_name, f'exec {container_name} -- journalctl -n {lines}', node_id=node_id)
            if len(output) > 1000:
                output = output[:1000] + '\n... (truncated)'
            embed = create_embed(f'📋 Logs - {container_name}', f'Last {lines} log lines', 1710618)
            add_field(embed, 'System Logs', f'```\n{output}\n```', False)
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=create_error_embed('Log Retrieval Failed', f'Error: {str(e)}'))
    @bot.command(name='vps-uptime')
    @is_admin()
    async def vps_uptime(ctx, container_name: str):
        node_id = find_node_id_for_container(container_name)
        uptime = await get_container_uptime(container_name, node_id)
        embed = create_info_embed('VPS Uptime', f'Uptime for `{container_name}`: {uptime}')
        await ctx.send(embed=embed)
    @bot.command(name='suspend-vps')
    @is_admin()
    async def suspend_vps(ctx, container_name: str, *, reason: str='Admin action'):
        node_id = find_node_id_for_container(container_name)
        found = False
        for uid, lst in vps_data.items():
            for vps in lst:
                if vps['container_name'] == container_name:
                    if vps.get('status')!= 'running':
                        await ctx.send(embed=create_error_embed('Cannot Suspend', 'VPS must be running to suspend.'))
                        return
                    else:
                        try:
                            await execute_lxc(container_name, f'stop {container_name}', node_id=node_id)
                            vps['status'] = 'stopped'
                            vps['suspended'] = True
                            if 'suspension_history' not in vps:
                                vps['suspension_history'] = []
                            vps['suspension_history'].append({'time': datetime.now().isoformat(), 'reason': reason, 'by': f'{ctx.author.name} ({ctx.author.id})'})
                            save_vps_data()
                        except Exception as e:
                            await ctx.send(embed=create_error_embed('Suspend Failed', str(e)))
                            return
                        try:
                            owner = await bot.fetch_user(int(uid))
                            embed = create_warning_embed('🚨 VPS Suspended', f'Your VPS `{container_name}` has been suspended by an admin.\n\n**Reason:** {reason}\n\nContact an admin to unsuspend.')
                            await owner.send(embed=embed)
                        except Exception as dm_e:
                            logger.error(f'Failed to DM owner {uid}: {dm_e}')
                        await ctx.send(embed=create_success_embed('VPS Suspended', f'VPS `{container_name}` suspended. Reason: {reason}'))
                        found = True
                        break
            if found:
                break
        if not found:
            await ctx.send(embed=create_error_embed('Not Found', f'VPS `{container_name}` not found.'))
    @bot.command(name='unsuspend-vps')
    @is_admin()
    async def unsuspend_vps(ctx, container_name: str):
        node_id = find_node_id_for_container(container_name)
        found = False
        for uid, lst in vps_data.items():
            for vps in lst:
                if vps['container_name'] == container_name:
                    if not vps.get('suspended', False):
                        await ctx.send(embed=create_error_embed('Not Suspended', 'VPS is not suspended.'))
                        return
                    else:
                        try:
                            vps['suspended'] = False
                            vps['status'] = 'running'
                            await execute_lxc(container_name, f'start {container_name}', node_id=node_id)
                            await apply_internal_permissions(container_name, node_id)
                            await recreate_port_forwards(container_name)
                            save_vps_data()
                            await ctx.send(embed=create_success_embed('VPS Unsuspended', f'VPS `{container_name}` unsuspended and started.'))
                            found = True
                        except Exception as e:
                            await ctx.send(embed=create_error_embed('Start Failed', str(e)))
                        try:
                            owner = await bot.fetch_user(int(uid))
                            embed = create_success_embed('🟢 VPS Unsuspended', f'Your VPS `{container_name}` has been unsuspended by an admin.\nYou can now manage it again.')
                            await owner.send(embed=embed)
                        except Exception as dm_e:
                            logger.error(f'Failed to DM owner {uid} about unsuspension: {dm_e}')
                        break
            if found:
                break
        if not found:
            await ctx.send(embed=create_error_embed('Not Found', f'VPS `{container_name}` not found.'))
    @bot.command(name='suspension-logs')
    @is_admin()
    async def suspension_logs(ctx, container_name: str=None):
        if container_name:
            found = None
            for lst in vps_data.values():
                for vps in lst:
                    if vps['container_name'] == container_name:
                        found = vps
                        break
                if found:
                    break
            if not found:
                await ctx.send(embed=create_error_embed('Not Found', f'VPS `{container_name}` not found.'))
                return
            else:
                history = found.get('suspension_history', [])
                if not history:
                    await ctx.send(embed=create_info_embed('No Suspensions', f'No suspension history for `{container_name}`.'))
                    return
                else:
                    embed = create_embed('Suspension History', f'For `{container_name}`')
                    text = []
                    for h in sorted(history, key=lambda x: x['time'], reverse=True)[:10]:
                        t = datetime.fromisoformat(h['time']).strftime('%Y-%m-%d %H:%M:%S')
                        text.append(f"**{t}** - {h['reason']} (by {h['by']})")
                    add_field(embed, 'History', '\n'.join(text), False)
                    if len(history) > 10:
                        add_field(embed, 'Note', 'Showing last 10 entries.')
                    await ctx.send(embed=embed)
        else:
            all_logs = []
            for uid, lst in vps_data.items():
                for vps in lst:
                    h = vps.get('suspension_history', [])
                    for event in sorted(h, key=lambda x: x['time'], reverse=True):
                        t = datetime.fromisoformat(event['time']).strftime('%Y-%m-%d %H:%M')
                        all_logs.append(f"**{t}** - VPS `{vps['container_name']}` (Owner: <@{uid}>) - {event['reason']} (by {event['by']})")
            if not all_logs:
                await ctx.send(embed=create_info_embed('No Suspensions', 'No suspension events recorded.'))
                return
            else:
                logs_text = '\n'.join(all_logs)
                chunks = [logs_text[i:i + 1024] for i in range(0, len(logs_text), 1024)]
                for idx, chunk in enumerate(chunks, 1):
                    embed = create_embed(f'Suspension Logs (Part {idx})', 'Global suspension events (newest first)')
                    add_field(embed, 'Events', chunk, False)
                    await ctx.send(embed=embed)
    @bot.command(name='apply-permissions')
    @is_admin()
    async def apply_permissions(ctx, container_name: str):
        node_id = find_node_id_for_container(container_name)
        await ctx.send(embed=create_info_embed('Applying Permissions', f'Applying advanced permissions to `{container_name}`...'))
        try:
            status = await get_container_status(container_name, node_id)
            was_running = status == 'running'
            if was_running:
                await execute_lxc(container_name, f'stop {container_name}', node_id=node_id)
            await apply_lxc_config(container_name, node_id)
            await execute_lxc(container_name, f'start {container_name}', node_id=node_id)
            await apply_internal_permissions(container_name, node_id)
            await recreate_port_forwards(container_name)
            for user_id, vps_list in vps_data.items():
                for vps in vps_list:
                    if vps['container_name'] == container_name:
                        vps['status'] = 'running'
                        vps['suspended'] = False
                        save_vps_data()
                        break
            await ctx.send(embed=create_success_embed('Permissions Applied', f'Advanced permissions applied to VPS `{container_name}`. Docker-ready with unprivileged ports!'))
        except Exception as e:
            await ctx.send(embed=create_error_embed('Apply Failed', f'Error: {str(e)}'))
    @bot.command(name='resource-check')
    @is_admin()
    async def resource_check(ctx):
        suspended_count = 0
        embed = create_info_embed('Resource Check', 'Checking all running VPS for high resource usage...')
        msg = await ctx.send(embed=embed)
        for user_id, vps_list in vps_data.items():
            for vps in vps_list:
                if vps.get('status') == 'running' and (not vps.get('suspended', False)) and (not vps.get('whitelisted', False)):
                            container = vps['container_name']
                            node_id = vps['node_id']
                            stats = await get_container_stats(container, node_id)
                            cpu = stats['cpu']
                            ram = stats['ram']['pct']
                            if cpu > CPU_THRESHOLD or ram > RAM_THRESHOLD:
                                reason = f'High resource usage: CPU {cpu:.1f}%, RAM {ram:.1f}% (threshold: {CPU_THRESHOLD}% CPU / {RAM_THRESHOLD}% RAM)'
                                logger.warning(f'Suspending {container}: {reason}')
                                try:
                                    await execute_lxc(container, f'stop {container}', node_id=node_id)
                                    vps['status'] = 'stopped'
                                    vps['suspended'] = True
                                    if 'suspension_history' not in vps:
                                        vps['suspension_history'] = []
                                    vps['suspension_history'].append({'time': datetime.now().isoformat(), 'reason': reason, 'by': 'Manual Resource Check'})
                                    save_vps_data()
                                    try:
                                        owner = await bot.fetch_user(int(user_id))
                                        warn_embed = create_warning_embed('🚨 VPS Auto-Suspended', f'Your VPS `{container}` has been suspended due to high resource usage.\n\n**Reason:** {reason}\n\nContact admin to unsuspend and address the issue.')
                                        await owner.send(embed=warn_embed)
                                    except Exception as dm_e:
                                        logger.error(f'Failed to DM owner {user_id}: {dm_e}')
                                    suspended_count += 1
                                except Exception as e:
                                    logger.error(f'Failed to suspend {container}: {e}')
                                else:
                                    pass
        final_embed = create_info_embed('Resource Check Complete', f'Checked all VPS. Suspended {suspended_count} high-usage VPS.')
        await msg.edit(embed=final_embed)
    @bot.command(name='whitelist-vps')
    @is_admin()
    async def whitelist_vps(ctx, container_name: str, action: str):
        if action.lower() not in ['add', 'remove']:
            await ctx.send(embed=create_error_embed('Invalid Action', f'Use: `{PREFIX}whitelist-vps <container> <add|remove>`'))
            return
        else:
            found = False
            for user_id, vps_list in vps_data.items():
                for vps in vps_list:
                    if vps['container_name'] == container_name:
                        if action.lower() == 'add':
                            vps['whitelisted'] = True
                            msg = 'added to whitelist (exempt from auto-suspension)'
                        else:
                            vps['whitelisted'] = False
                            msg = 'removed from whitelist'
                        save_vps_data()
                        await ctx.send(embed=create_success_embed('Whitelist Updated', f'VPS `{container_name}` {msg}.'))
                        found = True
                        break
                if found:
                    break
            if not found:
                await ctx.send(embed=create_error_embed('Not Found', f'VPS `{container_name}` not found.'))
    @bot.command(name='snapshot')
    @is_admin()
    async def snapshot_vps(ctx, container_name: str, snap_name: str='snap0'):
        node_id = find_node_id_for_container(container_name)
        await ctx.send(embed=create_info_embed('Creating Snapshot', f'Creating snapshot \'{snap_name}\' for `{container_name}`...'))
        try:
            await execute_lxc(container_name, f'snapshot {container_name} {snap_name}', node_id=node_id)
            await ctx.send(embed=create_success_embed('Snapshot Created', f'Snapshot \'{snap_name}\' created for VPS `{container_name}`.'))
        except Exception as e:
            await ctx.send(embed=create_error_embed('Snapshot Failed', f'Error: {str(e)}'))
            return
    @bot.command(name='list-snapshots')
    @is_admin()
    async def list_snapshots(ctx, container_name: str):
        node_id = find_node_id_for_container(container_name)
        try:
            result = await execute_lxc(container_name, f'snapshot list {container_name}', node_id=node_id)
            embed = create_info_embed(f'Snapshots for {container_name}', result)
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=create_error_embed('List Failed', f'Error: {str(e)}'))
    @bot.command(name='restore-snapshot')
    @is_admin()
    async def restore_snapshot(ctx, container_name: str, snap_name: str):
        node_id = find_node_id_for_container(container_name)
        await ctx.send(embed=create_warning_embed('Restore Snapshot', f'Restoring snapshot \'{snap_name}\' for `{container_name}` will overwrite current state. Continue?'))
        class RestoreConfirm(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=60)
            @discord.ui.button(label='Confirm Restore', style=discord.ButtonStyle.danger)
            async def confirm(self, inter: discord.Interaction, item: discord.ui.Button):
                await inter.response.defer()
                try:
                    await execute_lxc(container_name, f'stop {container_name}', node_id=node_id)
                    await execute_lxc(container_name, f'restore {container_name} {snap_name}', node_id=node_id)
                    await execute_lxc(container_name, f'start {container_name}', node_id=node_id)
                    await apply_internal_permissions(container_name, node_id)
                    await recreate_port_forwards(container_name)
                    for uid, lst in vps_data.items():
                        for vps in lst:
                            if vps['container_name'] == container_name:
                                vps['status'] = 'running'
                                vps['suspended'] = False
                                save_vps_data()
                                break
                    await inter.followup.send(embed=create_success_embed('Snapshot Restored', f'Restored \'{snap_name}\' for VPS `{container_name}`.'))
                except Exception as e:
                    await inter.followup.send(embed=create_error_embed('Restore Failed', f'Error: {str(e)}'))
                    return
            @discord.ui.button(label='Cancel', style=discord.ButtonStyle.secondary)
            async def cancel(self, inter: discord.Interaction, item: discord.ui.Button):
                await inter.response.edit_message(embed=create_info_embed('Cancelled', 'Snapshot restore cancelled.'))
        await ctx.send(view=RestoreConfirm())
    @bot.command(name='repair-ports')
    @is_admin()
    async def repair_ports(ctx, container_name: str):
        await ctx.send(embed=create_info_embed('Repairing Ports', f'Re-adding port forward devices for `{container_name}`...'))
        try:
            readded = await recreate_port_forwards(container_name)
            await ctx.send(embed=create_success_embed('Ports Repaired', f'Re-added {readded} port forwards for `{container_name}`.'))
        except Exception as e:
            await ctx.send(embed=create_error_embed('Repair Failed', f'Error: {str(e)}'))
    @bot.command(name='about')
    async def about(ctx):
        """Display bot information with premium branding"""
        total_users = len(vps_data)
        total_vps = sum((len(vps_list) for vps_list in vps_data.values()))
        latency = round(bot.latency * 1000)
        main_admin = await bot.fetch_user(MAIN_ADMIN_ID)
        embed = create_premium_embed(f'{BOT_NAME} VPS Manager', 'Professional VPS management platform for Discord communities')
        embed.set_thumbnail(url='https://i.imgur.com/dpatuSj.png')
        add_field(embed, 'Platform', f'```{BOT_NAME}```', True)
        add_field(embed, 'Version', f'```v{BOT_VERSION}```', True)
        add_field(embed, 'Status', format_status_badge(True, 'Online'), True)
        if latency < 100:
            latency_status = '🟢 Excellent'
        else:
            if latency < 200:
                latency_status = '🟡 Good'
            else:
                latency_status = '🔴 Poor'
        add_field(embed, 'Latency', f'```{latency}ms``` {latency_status}', True)
        add_field(embed, 'Uptime', f'```{get_uptime()}```', True)
        add_field(embed, 'Server', f'```{YOUR_SERVER_IP}```', True)
        stats_text = f"{format_list_item(f'Total VPS: {total_vps}')} 🖥️\n{format_list_item(f'Active Users: {total_users}')} 👥\n{format_list_item('Commands: 100+')} ⚡"
        add_field(embed, 'Statistics', stats_text, False)
        add_field(embed, 'Owner', main_admin.mention, True)
        add_field(embed, 'Developer', f'```{BOT_DEVELOPER}```', True)
        add_field(embed, 'Support', f'`{PREFIX}help`', True)
        features_text = f'{EmbedIcons.BULLET} Multi-node VPS management\n{EmbedIcons.BULLET} Advanced economy system\n{EmbedIcons.BULLET} Port forwarding & networking\n{EmbedIcons.BULLET} Real-time monitoring\n{EmbedIcons.BULLET} Premium UI/UX design'
        add_field(embed, 'Key Features', features_text, False)
        await ctx.send(embed=embed)
    @bot.command(name='balance', aliases=['bal', 'coins', 'wallet'])
    async def balance(ctx, user: discord.Member=None):
        """Check coin balance with premium card design"""
        target_user = user or ctx.author
        user_id = str(target_user.id)
        coins_data = await run_in_executor(get_user_coins, user_id)
        embed = create_card_embed('Coin Wallet', f'Financial overview for {target_user.mention}', color=EmbedColors.GOLD)
        balance_display = f"```\n{coins_data['balance']:,} coins\n```"
        add_field(embed, '💰 Current Balance', balance_display, False)
        add_field(embed, '� Total Earned', f"```{coins_data['total_earned']:,}```", True)
        add_field(embed, '📉 Total Spent', f"```{coins_data['total_spent']:,}```", True)
        add_field(embed, '💵 Net Worth', f"```{coins_data['balance']:,}```", True)
        invite_count = coins_data['invite_count']
        message_count = coins_data['message_count']
        voice_minutes = coins_data['voice_minutes']
        activity_text = f"{format_list_item(f'Invites: {invite_count}')} 👥\n{format_list_item(f'Messages: {message_count}')} 💬\n{format_list_item(f'Voice Time: {voice_minutes} min')} 🎤"
        add_field(embed, 'Activity Stats', activity_text, False)
        actions_text = f'`{PREFIX}daily` {EmbedIcons.ARROW} Claim daily reward\n`{PREFIX}work` {EmbedIcons.ARROW} Work for coins\n`{PREFIX}shop` {EmbedIcons.ARROW} Browse coin shop\n`{PREFIX}profile` {EmbedIcons.ARROW} View full profile'
        add_field(embed, 'Quick Actions', actions_text, False)
        await ctx.send(embed=embed)
    @bot.command(name='daily')
    async def daily_reward(ctx):
        # irreducible cflow, using cdg fallback
        """Claim daily coin reward with streak bonus"""
        user_id = str(ctx.author.id)
        if is_user_restricted(user_id):
            await ctx.send(embed=create_error_embed('❌ Access Restricted', 'Your account has been restricted from earning coins due to suspicious activity.\nContact an administrator for more information.'))
            return
        else:
            allowed, remaining = check_rate_limit(user_id, 'daily_claim', 2, 1440)
            if not allowed:
                log_security_event(user_id, 'daily_spam', 'Excessive daily claim attempts', 'medium')
                await ctx.send(embed=create_error_embed('⏰ Slow Down', 'You\'re trying to claim too frequently. Please wait before trying again.'))
                return
            else:
                def process_daily():
                    # irreducible cflow, using cdg fallback
                    conn = None
                    conn = get_db()
                    cur = conn.cursor()
                    cur.execute('SELECT value FROM settings WHERE key = ?', ('coins_daily_reward',))
                    row = cur.fetchone()
                    base_reward = int(row[0]) if row else 100
                    cur.execute('SELECT value FROM settings WHERE key = ?', ('streak_bonus_multiplier',))
                    row = cur.fetchone()
                    streak_bonus_mult = float(row[0]) if row else 0.1
                    cur.execute('SELECT value FROM settings WHERE key = ?', ('max_streak_bonus',))
                    row = cur.fetchone()
                    max_bonus = float(row[0]) if row else 2.0
                    cur.execute('SELECT * FROM user_coins WHERE user_id = ?', (user_id,))
                    coins_row = cur.fetchone()
                    if not coins_row:
                        cur.execute('INSERT INTO user_coins (user_id, balance, total_earned, total_spent, created_at)\n                               VALUES (?, 0, 0, 0, ?)', (user_id, datetime.now().isoformat()))
                        last_daily = None
                    else:
                        last_daily = coins_row['last_daily']
                    if last_daily:
                        last_claim = datetime.fromisoformat(last_daily)
                        if (datetime.now() - last_claim).total_seconds() < 86400:
                            time_left = 86400 - (datetime.now() - last_claim).total_seconds()
                            hours = int(time_left // 3600)
                            minutes = int(time_left % 3600 // 60)
                            conn.close()
                            return (False, hours, minutes, None, None, None)
                            cur.execute('SELECT * FROM user_streaks WHERE user_id = ?', (user_id,))
                            streak_row = cur.fetchone()
                            today = datetime.now().date().isoformat()
                            if not streak_row:
                                current_streak = 1
                                longest_streak = 1
                                bonus_multiplier = 1.0
                                cur.execute('INSERT INTO user_streaks \n                               (user_id, current_streak, longest_streak, last_claim_date, streak_bonus_multiplier)\n                               VALUES (?, 1, 1, ?, 1.0)', (user_id, today))
                            else:
                                last_claim = streak_row['last_claim_date']
                                current_streak = streak_row['current_streak']
                                longest_streak = streak_row['longest_streak']
                                yesterday = (datetime.now().date() - timedelta(days=1)).isoformat()
                                if last_claim == yesterday:
                                    current_streak += 1
                                    longest_streak = max(longest_streak, current_streak)
                                else:
                                    if last_claim!= today:
                                        current_streak = 1
                                bonus_multiplier = min(1.0 + current_streak * streak_bonus_mult, max_bonus)
                                cur.execute('UPDATE user_streaks \n                               SET current_streak = ?, longest_streak = ?, last_claim_date = ?, \n                                   streak_bonus_multiplier = ?\n                               WHERE user_id = ?', (current_streak, longest_streak, today, bonus_multiplier, user_id))
                            streak_data = {'current_streak': current_streak, 'longest_streak': longest_streak, 'bonus_multiplier': bonus_multiplier}
                            total_reward = int(base_reward * bonus_multiplier)
                            cur.execute('INSERT OR IGNORE INTO user_coins (user_id, balance, total_earned, total_spent, created_at)\n                           VALUES (?, 0, 0, 0, ?)', (user_id, datetime.now().isoformat()))
                            cur.execute('UPDATE user_coins \n                           SET balance = balance + ?, \n                               total_earned = total_earned + ?,\n                               last_daily = ?\n                           WHERE user_id = ?', (total_reward, total_reward, datetime.now().isoformat(), user_id))
                            cur.execute('INSERT INTO coin_transactions (user_id, amount, type, description, created_at)\n                           VALUES (?, ?, ?, ?, ?)', (user_id, total_reward, 'daily', f'Daily reward (Day {current_streak})', datetime.now().isoformat()))
                            cur.execute('SELECT balance FROM user_coins WHERE user_id = ?', (user_id,))
                            new_balance = cur.fetchone()[0]
                            conn.close()
                            return (True, base_reward, bonus_multiplier, streak_data, new_balance, None)
                                except Exception as e:
                                        if conn:
                                            conn.close()
                                        logger.error(f'Error in process_daily: {e}')
                                        return (False, 0, 0, None, None, str(e))
            result = await run_in_executor(process_daily)
            if not result[0]:
                _, hours, minutes, _, _, error = result
                if error:
                    embed = create_error_embed('❌ Error', f'An error occurred: {error}')
                else:
                    embed = create_warning_embed('⏰ Daily Reward', f'You\'ve already claimed your daily reward!\nCome back in **{hours}h {minutes}m**')
                await ctx.send(embed=embed)
                    return
                _, base_reward, streak_bonus, streak_data, new_balance, _ = result
                total_reward = int(base_reward * streak_bonus)
                embed = create_success_embed('🎁 Daily Reward Claimed!', f"**Base Reward:** {base_reward} coins\n**Streak Bonus:** {int((streak_bonus - 1) * 100)}% (Day {streak_data['current_streak']} 🔥)\n**Total Earned:** {total_reward:,} coins\n**New Balance:** {new_balance:,} coins\n\n**Longest Streak:** {streak_data['longest_streak']} days")
                add_field(embed, '💡 Tip', 'Claim daily to build your streak and earn more coins!\nNext claim: Tomorrow at this time', False)
                await ctx.send(embed=embed)
                except Exception as e:
                        logger.error(f'Error in daily_reward command: {e}')
                        embed = create_error_embed('❌ Error', 'An error occurred while processing your daily reward. Please try again.')
                        await ctx.send(embed=embed)
    @bot.command(name='leaderboard', aliases=['lb', 'top'])
    async def leaderboard(ctx):
        """Show coin leaderboard"""
        limit = int(get_setting('leaderboard_top_count', 10))
        def get_leaderboard_data():
            top_users = get_coin_leaderboard(limit)
            user_id = str(ctx.author.id)
            conn = get_db()
            cur = conn.cursor()
            cur.execute('SELECT COUNT(*) + 1 FROM user_coins \n                       WHERE balance > (SELECT balance FROM user_coins WHERE user_id = ?)', (user_id,))
            user_rank = cur.fetchone()[0]
            user_coins = get_user_coins(user_id)
            conn.close()
            return (top_users, user_rank, user_coins)
        top_users, user_rank, user_coins = await run_in_executor(get_leaderboard_data)
        embed = create_embed('🏆 Coin Leaderboard', f'Top {limit} richest users', 15844367)
        if not top_users:
            add_field(embed, 'No Data', 'No users have earned coins yet!', False)
        else:
            leaderboard_text = []
            medals = ['🥇', '🥈', '🥉']
            for idx, user_data in enumerate(top_users, 1):
                try:
                    user = await bot.fetch_user(int(user_data['user_id']))
                    medal = medals[idx - 1] if idx <= 3 else f'**{idx}.**'
                    leaderboard_text.append(f"{medal} {user.name} - **{user_data['balance']:,} coins**\n   ↳ Earned: {user_data['total_earned']:,} | Invites: {user_data['invite_count']} | Messages: {user_data['message_count']}")
                except:
                    pass
                else:
                    pass
            add_field(embed, 'Top Users', '\n\n'.join(leaderboard_text), False)
        if user_rank > limit:
            add_field(embed, 'Your Rank', f"**#{user_rank}** - {user_coins['balance']:,} coins", False)
        await ctx.send(embed=embed)
    @bot.command(name='transactions', aliases=['history', 'txn'])
    async def transactions(ctx, limit: int=10):
        """View recent coin transactions"""
        user_id = str(ctx.author.id)
        if limit > 20:
            limit = 20
        txns = await run_in_executor(get_user_transactions, user_id, limit)
        embed = create_info_embed('📜 Transaction History', f'Last {len(txns)} transactions for {ctx.author.mention}')
        if not txns:
            add_field(embed, 'No Transactions', 'You haven\'t earned or spent any coins yet!', False)
        else:
            txn_text = []
            for txn in txns:
                amount = txn['amount']
                emoji = '➕' if amount > 0 else '➖'
                color = '+' if amount > 0 else ''
                created = datetime.fromisoformat(txn['created_at']).strftime('%m/%d %H:%M')
                txn_text.append(f"{emoji} **{color}{amount:,} coins** - {txn['type']}\n   ↳ {txn['description'] or 'No description'} ({created})")
            add_field(embed, 'Recent Transactions', '\n\n'.join(txn_text[:10]), False)
            if len(txns) > 10:
                add_field(embed, 'Note', f'Showing 10 of {len(txns)} transactions', False)
        await ctx.send(embed=embed)
    @bot.command(name='renew')
    async def renew_vps_command(ctx, vps_number: int=None, days: int=1):
        # irreducible cflow, using cdg fallback
        """Renew your VPS using coins"""
        user_id = str(ctx.author.id)
        if vps_number is None:
            await ctx.send(embed=create_error_embed('Usage', f'Usage: `{PREFIX}renew <vps_number> [days]`\nExample: `{PREFIX}renew 1 7` (renew VPS #1 for 7 days)'))
            return
        else:
            if days < 1 or days > 365:
                await ctx.send(embed=create_error_embed('Invalid Duration', 'Days must be between 1 and 365'))
                return
            else:
                vps_list = vps_data.get(user_id, [])
                if vps_number < 1 or vps_number > len(vps_list):
                    await ctx.send(embed=create_error_embed('Invalid VPS', f'You don\'t have VPS #{vps_number}. Use `{PREFIX}myvps` to see your VPS.'))
                    return
                else:
                    vps = vps_list[vps_number - 1]
                    cost_per_day = int(get_setting('coins_vps_renewal_1day', 50))
                    total_cost = cost_per_day * days
                    coins_data = await run_in_executor(get_user_coins, user_id)
                    if coins_data['balance'] < total_cost:
                        needed = total_cost - coins_data['balance']
                        await ctx.send(embed=create_error_embed('Insufficient Coins', f'You need **{total_cost:,} coins** to renew for {days} day(s).\nYou have: **{coins_data['balance']:,} coins**\nYou need: **{needed:,} more coins**\n\nUse `{PREFIX}coinhelp` to see how to earn coins!'))
                    else:
                        embed = create_warning_embed('💰 Confirm VPS Renewal', f"**VPS:** `{vps['container_name']}`\n**Duration:** {days} day(s)\n**Cost:** {total_cost:,} coins\n**Your Balance:** {coins_data['balance']:,} coins\n**After Renewal:** {coins_data['balance'] - total_cost:,} coins\n\nReact with ✅ to confirm or ❌ to cancel")
                        msg = await ctx.send(embed=embed)
                        await msg.add_reaction('✅')
                        await msg.add_reaction('❌')
                        def check(reaction, user):
                            return user == ctx.author and str(reaction.emoji) in ['✅', '❌'] and (reaction.message.id == msg.id)
            reaction, user = await bot.wait_for('reaction_add', timeout=30.0, check=check)
            if str(reaction.emoji) == '❌':
                await msg.edit(embed=create_info_embed('Cancelled', 'VPS renewal cancelled.'))
                    return
                async def process_renewal():
                    success, new_balance = remove_coins(user_id, total_cost, 'vps_renewal', f'Renewed VPS #{vps_number} for {days} days')
                    return (success, new_balance)
                success, new_balance = await run_in_executor(process_renewal)
                if not success:
                    await msg.edit(embed=create_error_embed('Error', 'Failed to process payment.'))
                        return
                    vps_id = vps.get('id')
                    if vps_id:
                        renew_vps(vps_id, days)
                        if vps.get('expires_at'):
                            current_expiry = datetime.fromisoformat(vps['expires_at'])
                            if current_expiry < datetime.now():
                                current_expiry = datetime.now()
                        else:
                            current_expiry = datetime.now()
                        new_expiry = current_expiry + timedelta(days=days)
                        vps['expires_at'] = new_expiry.isoformat()
                        vps['duration_days'] = vps.get('duration_days', 0) + days
                        if vps.get('suspended'):
                            vps['suspended'] = False
                            vps['status'] = 'stopped'
                        save_vps_data()
                        success_embed = create_success_embed('✅ VPS Renewed Successfully!', f"**VPS:** `{vps['container_name']}`\n**Extended by:** {days} day(s)\n**New Expiry:** {new_expiry.strftime('%Y-%m-%d %H:%M:%S')}\n**Cost:** {total_cost:,} coins\n**New Balance:** {new_balance:,} coins\n\nYour VPS has been renewed! 🎉")
                        await msg.edit(embed=success_embed)
                except asyncio.TimeoutError:
                    await msg.edit(embed=create_info_embed('Timeout', 'Renewal request timed out.'))
                        return
    @bot.command(name='admin-renew', aliases=['arenew', 'set-expiry', 'extend-vps'])
    @is_admin()
    async def admin_renew_vps(ctx, user: discord.Member, vps_number: int, days: int):
        """Admin command to set/extend VPS expiry without coins"""
        if days < 1 or days > 365:
            await ctx.send(embed=create_error_embed('Invalid Duration', 'Days must be between 1 and 365'))
            return
        else:
            user_id = str(user.id)
            vps_list = vps_data.get(user_id, [])
            if not vps_list:
                await ctx.send(embed=create_error_embed('No VPS Found', f'{user.mention} doesn\'t have any VPS.'))
                return
            else:
                if vps_number < 1 or vps_number > len(vps_list):
                    await ctx.send(embed=create_error_embed('Invalid VPS', f'{user.mention} doesn\'t have VPS #{vps_number}.\nThey have {len(vps_list)} VPS total.'))
                    return
                else:
                    vps = vps_list[vps_number - 1]
                    container_name = vps['container_name']
                    if vps.get('expires_at'):
                        current_expiry = datetime.fromisoformat(vps['expires_at'])
                        if current_expiry < datetime.now():
                            base_time = datetime.now()
                        else:
                            base_time = current_expiry
                    else:
                        base_time = datetime.now()
                    new_expiry = base_time + timedelta(days=days)
                    vps['expires_at'] = new_expiry.isoformat()
                    vps['duration_days'] = vps.get('duration_days', 0) + days
                    was_suspended = vps.get('suspended', False)
                    if was_suspended:
                        vps['suspended'] = False
                        vps['status'] = 'stopped'
                    save_vps_data()
                    vps_id = vps.get('id')
                    if vps_id:
                        try:
                            renew_vps(vps_id, days)
                        except Exception as e:
                            logger.warning(f'Failed to update VPS expiry in database: {e}')
                    expiry_info = format_expiry_time(new_expiry.isoformat())
                    embed = create_success_embed('✅ VPS Expiry Updated (Admin)', f"**User:** {user.mention}\n**VPS:** `{container_name}` (#{vps_number})\n**Extended by:** {days} day(s)\n**New Expiry:** {new_expiry.strftime('%Y-%m-%d %H:%M:%S')}\n**Status:** {expiry_info['text']}\n**Total Duration:** {vps.get('duration_days', 0)} days")
                    if was_suspended:
                        add_field(embed, '🔓 Unsuspended', f'VPS was suspended and has been unsuspended.\nUser can start it with `{PREFIX}manage`', False)
                    add_field(embed, '💡 Note', 'This renewal was done by admin (no coins charged)', False)
                    await ctx.send(embed=embed)
                    try:
                        dm_embed = create_success_embed('🎁 VPS Extended by Admin!', f"An admin has extended your VPS!\n\n**VPS:** `{container_name}` (#{vps_number})\n**Extended by:** {days} day(s)\n**New Expiry:** {new_expiry.strftime('%Y-%m-%d %H:%M:%S')}\n**Status:** {expiry_info['text']}")
                        if was_suspended:
                            add_field(dm_embed, '🔓 Unsuspended', f'Your VPS was unsuspended! Use `{PREFIX}manage` to start it.', False)
                        await user.send(embed=dm_embed)
                    except discord.Forbidden:
                        await ctx.send(embed=create_info_embed('DM Failed', f'Couldn\'t send DM to {user.mention}. They may have DMs disabled.'))
                    logger.info(f'Admin {ctx.author.name} extended VPS {container_name} for {user.name} by {days} days')
    @bot.command(name='renewconfig', aliases=['renewal-config', 'renew-settings'])
    @is_admin()
    async def renewal_config(ctx, setting: str=None, value: str=None):
        # irreducible cflow, using cdg fallback
        """Configure VPS renewal system settings"""
        global DEFAULT_VPS_DURATION_DAYS
        if setting is None:
            cost_1day = int(get_setting('coins_vps_renewal_1day', 50))
            cost_7days = int(get_setting('coins_vps_renewal_7days', 300))
            cost_30days = int(get_setting('coins_vps_renewal_30days', 1000))
            default_days = int(get_setting('default_vps_duration_days', 7))
            warning_hours = int(get_setting('vps_expiry_warning_hours', 24))
            embed = create_info_embed('💰 VPS Renewal Configuration', 'Current renewal system settings')
            add_field(embed, '💵 Renewal Costs', f'**1 Day:** {cost_1day} coins\n**7 Days:** {cost_7days} coins\n**30 Days:** {cost_30days} coins', True)
            add_field(embed, '⏰ Expiration Settings', f'**Default Duration:** {default_days} days\n**Warning Time:** {warning_hours} hours before', True)
            add_field(embed, '📝 Available Settings', '`cost_1day` - Cost for 1 day renewal\n`cost_7days` - Cost for 7 days renewal\n`cost_30days` - Cost for 30 days renewal\n`default_days` - Default VPS duration\n`warning_hours` - Hours before expiry to warn', False)
            add_field(embed, '💡 Usage', f'`{PREFIX}renewconfig <setting> <value>`\nExample: `{PREFIX}renewconfig cost_1day 100`', False)
            await ctx.send(embed=embed)
            return
        else:
            setting = setting.lower()
            valid_settings = {'cost_1day': 'coins_vps_renewal_1day', 'cost_7days': 'coins_vps_renewal_7days', 'cost_30days': 'coins_vps_renewal_30days', 'default_days': 'default_vps_duration_days', 'warning_hours': 'vps_expiry_warning_hours'}
            if setting not in valid_settings:
                await ctx.send(embed=create_error_embed('Invalid Setting', f"Valid settings: {', '.join(valid_settings.keys())}"))
                return
            else:
                if value is None:
                    await ctx.send(embed=create_error_embed('Missing Value', f'Usage: `{PREFIX}renewconfig {setting} <value>`'))
                    return
            int_value = int(value)
            if int_value < 1:
                await ctx.send(embed=create_error_embed('Invalid Value', 'Value must be positive'))
                    return
                db_key = valid_settings[setting]
                set_setting(db_key, str(int_value))
                if setting == 'default_days':
                    DEFAULT_VPS_DURATION_DAYS = int_value
                setting_names = {'cost_1day': '1 Day Renewal Cost', 'cost_7days': '7 Days Renewal Cost', 'cost_30days': '30 Days Renewal Cost', 'default_days': 'Default VPS Duration', 'warning_hours': 'Expiry Warning Time'}
                embed = create_success_embed('✅ Setting Updated', f"**{setting_names[setting]}** has been updated!\n\n**New Value:** {int_value} {('coins' if 'cost' in setting else 'days' if 'days' in setting else 'hours')}\n\nThis will apply to all new renewals and VPS creations.")
                await ctx.send(embed=embed)
                logger.info(f'Renewal config updated by {ctx.author.name}: {setting} = {int_value}')
                except ValueError:
                    await ctx.send(embed=create_error_embed('Invalid Value', 'Value must be a number'))
                        return
    @bot.command(name='renewprices', aliases=['renewal-prices', 'renew-cost'])
    async def renewal_prices(ctx):
        """Show VPS renewal pricing"""
        cost_1day = int(get_setting('coins_vps_renewal_1day', 50))
        cost_7days = int(get_setting('coins_vps_renewal_7days', 300))
        cost_30days = int(get_setting('coins_vps_renewal_30days', 1000))
        per_day_7 = cost_7days / 7
        per_day_30 = cost_30days / 30
        savings_7 = cost_1day * 7 - cost_7days
        savings_30 = cost_1day * 30 - cost_30days
        savings_7_pct = savings_7 / (cost_1day * 7) * 100
        savings_30_pct = savings_30 / (cost_1day * 30) * 100
        embed = create_info_embed('💰 VPS Renewal Pricing', 'Extend your VPS subscription with coins')
        add_field(embed, '📅 1 Day Package', f'**Cost:** {cost_1day} coins\n**Per Day:** {cost_1day} coins\n**Best For:** Short-term testing', True)
        add_field(embed, '📅 7 Days Package', f'**Cost:** {cost_7days} coins\n**Per Day:** {per_day_7:.1f} coins\n**Save:** {savings_7:.0f} coins ({savings_7_pct:.0f}%)\n**Best For:** Weekly projects', True)
        add_field(embed, '📅 30 Days Package', f'**Cost:** {cost_30days} coins\n**Per Day:** {per_day_30:.1f} coins\n**Save:** {savings_30:.0f} coins ({savings_30_pct:.0f}%)\n**Best For:** Long-term hosting', True)
        add_field(embed, '💡 How to Renew', f'`{PREFIX}renew <vps_number> <days>`\nExample: `{PREFIX}renew 1 7` (renew VPS #1 for 7 days)', False)
        add_field(embed, '💵 Earn Coins', f'`{PREFIX}daily` - Daily reward\n`{PREFIX}work` - Work for coins\n`{PREFIX}coinhelp` - More ways to earn', False)
        embed.set_footer(text=f'{BOT_NAME} • Longer packages = Better value!')
        await ctx.send(embed=embed)
    @bot.command(name='create-deploy-plan', aliases=['add-deploy-plan', 'new-deploy-plan'])
    @is_admin()
    async def create_deploy_plan(ctx, name: str, ram: int, cpu: int, disk: int, days: int, cost: int, icon: str='📦'):
        # irreducible cflow, using cdg fallback
        """Create a new deployment plan"""
        if ram < 1 or cpu < 1 or disk < 1 or (days < 1) or (cost < 1):
            await ctx.send(embed=create_error_embed('Invalid Values', 'All values must be positive numbers.'))
            return
            conn = get_db()
            cur = conn.cursor()
            cur.execute('SELECT id FROM deploy_plans WHERE name = ?', (name,))
            if cur.fetchone():
                conn.close()
                await ctx.send(embed=create_error_embed('Plan Exists', f'A deployment plan named **{name}** already exists.\nUse `{PREFIX}edit-deploy-plan` to modify it.'))
                    return
                cur.execute('INSERT INTO deploy_plans \n                       (name, description, ram_gb, cpu_cores, disk_gb, duration_days, cost_coins, icon, created_at)\n                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', (name, f'{ram}GB RAM, {cpu} CPU, {disk}GB Disk for {days} days', ram, cpu, disk, days, cost, icon, datetime.now().isoformat()))
                plan_id = cur.lastrowid
                conn.commit()
                conn.close()
                embed = create_success_embed('✅ Deployment Plan Created', f"**Plan ID:** {plan_id}\n**Name:** {icon} {name}\n**Resources:** {ram}GB RAM, {cpu} CPU, {disk}GB Disk\n**Duration:** {days} day{('s' if days > 1 else '')}\n**Cost:** {cost:,} coins\n\nUsers can now deploy with: `{PREFIX}deploy {plan_id}`")
                await ctx.send(embed=embed)
                logger.info(f'Admin {ctx.author.name} created deploy plan: {name}')
                except Exception as e:
                        await ctx.send(embed=create_error_embed('Creation Failed', f'Error: {str(e)}'))
                        logger.error(f'Failed to create deploy plan: {e}')
    @bot.command(name='edit-deploy-plan', aliases=['update-deploy-plan', 'modify-deploy-plan'])
    @is_admin()
    async def edit_deploy_plan(ctx, plan_id: int, field: str, value: str):
        # irreducible cflow, using cdg fallback
        """Edit a deployment plan"""
        valid_fields = ['name', 'ram', 'cpu', 'disk', 'days', 'cost', 'icon', 'description', 'active']
        if field.lower() not in valid_fields:
            await ctx.send(embed=create_error_embed('Invalid Field', f"Valid fields: {', '.join(valid_fields)}"))
            return
            conn = get_db()
            cur = conn.cursor()
            cur.execute('SELECT * FROM deploy_plans WHERE id = ?', (plan_id,))
            plan = cur.fetchone()
            if not plan:
                conn.close()
                await ctx.send(embed=create_error_embed('Plan Not Found', f'Deployment plan #{plan_id} not found.'))
                    return
                plan = dict(plan)
                field_map = {'name': 'name', 'ram': 'ram_gb', 'cpu': 'cpu_cores', 'disk': 'disk_gb', 'days': 'duration_days', 'cost': 'cost_coins', 'icon': 'icon', 'description': 'description', 'active': 'active'}
                db_field = field_map[field.lower()]
                if field.lower() in ['ram', 'cpu', 'disk', 'days', 'cost']:
                    value = int(value)
                    if value < 1:
                        raise ValueError('Must be positive')
                    if field.lower() == 'active':
                        value = 1 if value.lower() in ['1', 'true', 'yes', 'active'] else 0
                        cur.execute(f'UPDATE deploy_plans SET {db_field} = ? WHERE id = ?', (value, plan_id))
                        conn.commit()
                        conn.close()
                        embed = create_success_embed('✅ Plan Updated', f"**Plan ID:** {plan_id}\n**Plan Name:** {plan['name']}\n**Updated Field:** {field}\n**New Value:** {value}\n\nChanges will apply to new deployments.")
                        await ctx.send(embed=embed)
                        logger.info(f'Admin {ctx.author.name} updated deploy plan {plan_id}: {field} = {value}')
                        except ValueError:
                            await ctx.send(embed=create_error_embed('Invalid Value', f'{field} must be a positive number.'))
                            conn.close()
                                return
                    except Exception as e:
                            await ctx.send(embed=create_error_embed('Update Failed', f'Error: {str(e)}'))
                            logger.error(f'Failed to update deploy plan: {e}')
                                return
    @bot.command(name='delete-deploy-plan', aliases=['remove-deploy-plan'])
    @is_admin()
    async def delete_deploy_plan(ctx, plan_id: int):
        # irreducible cflow, using cdg fallback
        """Delete a deployment plan"""
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT * FROM deploy_plans WHERE id = ?', (plan_id,))
        plan = cur.fetchone()
        if not plan:
            conn.close()
            await ctx.send(embed=create_error_embed('Plan Not Found', f'Deployment plan #{plan_id} not found.'))
                return
            plan = dict(plan)
            cur.execute('DELETE FROM deploy_plans WHERE id = ?', (plan_id,))
            conn.commit()
            conn.close()
            embed = create_success_embed('✅ Plan Deleted', f"**Plan ID:** {plan_id}\n**Plan Name:** {plan['icon']} {plan['name']}\n**Resources:** {plan['ram_gb']}GB RAM, {plan['cpu_cores']} CPU, {plan['disk_gb']}GB Disk\n\nThis plan is no longer available for deployment.")
            await ctx.send(embed=embed)
            logger.info(f"Admin {ctx.author.name} deleted deploy plan {plan_id}: {plan['name']}")
            except Exception as e:
                    await ctx.send(embed=create_error_embed('Deletion Failed', f'Error: {str(e)}'))
                    logger.error(f'Failed to delete deploy plan: {e}')
    @bot.command(name='create-resource-plan', aliases=['add-resource-plan', 'new-resource-plan'])
    @is_admin()
    async def create_resource_plan(ctx, name: str, ram: int, cpu: int, disk: int, cost: int, icon: str='⚡'):
        # irreducible cflow, using cdg fallback
        """Create a new resource upgrade plan"""
        if ram < 1 or cpu < 1 or disk < 1 or (cost < 1):
            await ctx.send(embed=create_error_embed('Invalid Values', 'All values must be positive numbers.'))
            return
            conn = get_db()
            cur = conn.cursor()
            cur.execute('SELECT id FROM resource_plans WHERE name = ?', (name,))
            if cur.fetchone():
                conn.close()
                await ctx.send(embed=create_error_embed('Plan Exists', f'A resource plan named **{name}** already exists.\nUse `{PREFIX}edit-resource-plan` to modify it.'))
                    return
                cur.execute('INSERT INTO resource_plans \n                       (name, description, ram_gb, cpu_cores, disk_gb, upgrade_cost, icon, created_at)\n                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)', (name, f'{ram}GB RAM, {cpu} CPU, {disk}GB Disk', ram, cpu, disk, cost, icon, datetime.now().isoformat()))
                plan_id = cur.lastrowid
                conn.commit()
                conn.close()
                embed = create_success_embed('✅ Resource Plan Created', f'**Plan ID:** {plan_id}\n**Name:** {icon} {name}\n**Resources:** {ram}GB RAM, {cpu} CPU, {disk}GB Disk\n**Upgrade Cost:** {cost:,} coins\n\nUsers can now upgrade with: `{PREFIX}upgrade <vps_id> {plan_id}`')
                await ctx.send(embed=embed)
                logger.info(f'Admin {ctx.author.name} created resource plan: {name}')
                except Exception as e:
                        await ctx.send(embed=create_error_embed('Creation Failed', f'Error: {str(e)}'))
                        logger.error(f'Failed to create resource plan: {e}')
    @bot.command(name='edit-resource-plan', aliases=['update-resource-plan', 'modify-resource-plan'])
    @is_admin()
    async def edit_resource_plan(ctx, plan_id: int, field: str, value: str):
        # irreducible cflow, using cdg fallback
        """Edit a resource upgrade plan"""
        valid_fields = ['name', 'ram', 'cpu', 'disk', 'cost', 'icon', 'description', 'active']
        if field.lower() not in valid_fields:
            await ctx.send(embed=create_error_embed('Invalid Field', f"Valid fields: {', '.join(valid_fields)}"))
            return
            conn = get_db()
            cur = conn.cursor()
            cur.execute('SELECT * FROM resource_plans WHERE id = ?', (plan_id,))
            plan = cur.fetchone()
            if not plan:
                conn.close()
                await ctx.send(embed=create_error_embed('Plan Not Found', f'Resource plan #{plan_id} not found.'))
                    return
                plan = dict(plan)
                field_map = {'name': 'name', 'ram': 'ram_gb', 'cpu': 'cpu_cores', 'disk': 'disk_gb', 'cost': 'upgrade_cost', 'icon': 'icon', 'description': 'description', 'active': 'active'}
                db_field = field_map[field.lower()]
                if field.lower() in ['ram', 'cpu', 'disk', 'cost']:
                    value = int(value)
                    if value < 1:
                        raise ValueError('Must be positive')
                    if field.lower() == 'active':
                        value = 1 if value.lower() in ['1', 'true', 'yes', 'active'] else 0
                        cur.execute(f'UPDATE resource_plans SET {db_field} = ? WHERE id = ?', (value, plan_id))
                        conn.commit()
                        conn.close()
                        embed = create_success_embed('✅ Plan Updated', f"**Plan ID:** {plan_id}\n**Plan Name:** {plan['name']}\n**Updated Field:** {field}\n**New Value:** {value}\n\nChanges will apply to new upgrades.")
                        await ctx.send(embed=embed)
                        logger.info(f'Admin {ctx.author.name} updated resource plan {plan_id}: {field} = {value}')
                        except ValueError:
                            await ctx.send(embed=create_error_embed('Invalid Value', f'{field} must be a positive number.'))
                            conn.close()
                    except Exception as e:
                            await ctx.send(embed=create_error_embed('Update Failed', f'Error: {str(e)}'))
                            logger.error(f'Failed to update resource plan: {e}')
                                return
    @bot.command(name='delete-resource-plan', aliases=['remove-resource-plan'])
    @is_admin()
    async def delete_resource_plan(ctx, plan_id: int):
        # irreducible cflow, using cdg fallback
        """Delete a resource upgrade plan"""
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT * FROM resource_plans WHERE id = ?', (plan_id,))
        plan = cur.fetchone()
        if not plan:
            conn.close()
            await ctx.send(embed=create_error_embed('Plan Not Found', f'Resource plan #{plan_id} not found.'))
                return
            plan = dict(plan)
            cur.execute('DELETE FROM resource_plans WHERE id = ?', (plan_id,))
            conn.commit()
            conn.close()
            embed = create_success_embed('✅ Plan Deleted', f"**Plan ID:** {plan_id}\n**Plan Name:** {plan['icon']} {plan['name']}\n**Resources:** {plan['ram_gb']}GB RAM, {plan['cpu_cores']} CPU, {plan['disk_gb']}GB Disk\n\nThis plan is no longer available for upgrades.")
            await ctx.send(embed=embed)
            logger.info(f"Admin {ctx.author.name} deleted resource plan {plan_id}: {plan['name']}")
            except Exception as e:
                    await ctx.send(embed=create_error_embed('Deletion Failed', f'Error: {str(e)}'))
                    logger.error(f'Failed to delete resource plan: {e}')
    @bot.command(name='list-deploy-plans', aliases=['all-deploy-plans'])
    @is_admin()
    async def list_deploy_plans_admin(ctx):
        """List all deployment plans (including inactive)"""
        plans = get_deploy_plans(active_only=False)
        if not plans:
            await ctx.send(embed=create_error_embed('No Plans', 'No deployment plans exist. Create one with `{PREFIX}create-deploy-plan`.'))
            return
        else:
            embed = create_info_embed('📋 All Deployment Plans (Admin View)', 'All deployment plans including inactive ones')
            for plan in plans:
                status = '✅ Active' if plan['active'] else '❌ Inactive'
                plan_info = f"**ID:** {plan['id']}\n**Status:** {status}\n**Resources:** {plan['ram_gb']}GB RAM, {plan['cpu_cores']} CPU, {plan['disk_gb']}GB\n**Duration:** {plan['duration_days']} day(s)\n**Cost:** {plan['cost_coins']:,} coins\n**Edit:** `{PREFIX}edit-deploy-plan {plan['id']} <field> <value>`\n**Delete:** `{PREFIX}delete-deploy-plan {plan['id']}`"
                add_field(embed, f"{plan['icon']} {plan['name']}", plan_info, True)
            add_field(embed, '💡 Management', f'**Create:** `{PREFIX}create-deploy-plan <name> <ram> <cpu> <disk> <days> <cost> [icon]`\n**Edit:** `{PREFIX}edit-deploy-plan <id> <field> <value>`\n**Delete:** `{PREFIX}delete-deploy-plan <id>`', False)
            await ctx.send(embed=embed)
    @bot.command(name='list-resource-plans', aliases=['all-resource-plans'])
    @is_admin()
    async def list_resource_plans_admin(ctx):
        """List all resource plans (including inactive)"""
        plans = get_resource_plans(active_only=False)
        if not plans:
            await ctx.send(embed=create_error_embed('No Plans', f'No resource plans exist. Create one with `{PREFIX}create-resource-plan`.'))
            return
        else:
            embed = create_info_embed('📋 All Resource Plans (Admin View)', 'All resource upgrade plans including inactive ones')
            for plan in plans:
                status = '✅ Active' if plan['active'] else '❌ Inactive'
                plan_info = f"**ID:** {plan['id']}\n**Status:** {status}\n**Resources:** {plan['ram_gb']}GB RAM, {plan['cpu_cores']} CPU, {plan['disk_gb']}GB\n**Cost:** {plan['upgrade_cost']:,} coins\n**Edit:** `{PREFIX}edit-resource-plan {plan['id']} <field> <value>`\n**Delete:** `{PREFIX}delete-resource-plan {plan['id']}`"
                add_field(embed, f"{plan['icon']} {plan['name']}", plan_info, True)
            add_field(embed, '💡 Management', f'**Create:** `{PREFIX}create-resource-plan <name> <ram> <cpu> <disk> <cost> [icon]`\n**Edit:** `{PREFIX}edit-resource-plan <id> <field> <value>`\n**Delete:** `{PREFIX}delete-resource-plan <id>`', False)
            await ctx.send(embed=embed)
    @bot.command(name='create-coupon', aliases=['add-coupon', 'new-coupon'])
    @is_admin()
    async def create_coupon_command(ctx, coins: int, code: str, max_uses: int=None, expires_in_days: int=None):
        """Create a new coupon code\n    \n    Usage: !create-coupon <coins> <code> [max_uses] [expires_in_days]\n    \n    Examples:\n    !create-coupon 1000 WELCOME2024\n    !create-coupon 500 EVENT50 100\n    !create-coupon 2000 LIMITED 50 7\n    """
        if coins < 1:
            await ctx.send(embed=create_error_embed('Invalid Amount', 'Coins must be a positive number.'))
            return
        else:
            if len(code) < 3:
                await ctx.send(embed=create_error_embed('Invalid Code', 'Coupon code must be at least 3 characters long.'))
                return
            else:
                if max_uses is not None and max_uses < 1:
                    await ctx.send(embed=create_error_embed('Invalid Max Uses', 'Max uses must be a positive number or leave blank for unlimited.'))
                    return
                else:
                    expires_at = None
                    if expires_in_days:
                        if expires_in_days < 1:
                            await ctx.send(embed=create_error_embed('Invalid Expiry', 'Expiry days must be positive or leave blank for never.'))
                            return
                        else:
                            expires_at = (datetime.now() + timedelta(days=expires_in_days)).isoformat()
                    try:
                        async def create():
                            return create_coupon(code, coins, max_uses, expires_at, str(ctx.author.id), f'Created by {ctx.author.name}')
                        coupon_id = await run_in_executor(create)
                        expiry_text = f'{expires_in_days} days' if expires_in_days else 'Never'
                        uses_text = f'{max_uses} uses' if max_uses else 'Unlimited'
                        embed = create_success_embed('✅ Coupon Created', f'**Code:** `{code.upper()}`\n**Coins:** {coins:,}\n**Max Uses:** {uses_text}\n**Expires:** {expiry_text}\n**Coupon ID:** {coupon_id}\n\nUsers can redeem with: `{PREFIX}redeem {code.upper()}`')
                        await ctx.send(embed=embed)
                        logger.info(f'Admin {ctx.author.name} created coupon {code} for {coins} coins')
                    except Exception as e:
                        if 'UNIQUE constraint failed' in str(e):
                            await ctx.send(embed=create_error_embed('Code Exists', f'Coupon code `{code.upper()}` already exists.\nUse a different code or delete the existing one.'))
                        else:
                            await ctx.send(embed=create_error_embed('Creation Failed', f'Error: {str(e)}'))
                        logger.error(f'Failed to create coupon: {e}')
    @bot.command(name='list-coupons', aliases=['all-coupons', 'coupons'])
    @is_admin()
    async def list_coupons_command(ctx, show_all: str=None):
        """List all coupon codes (admin only)\n    \n    Usage: !list-coupons [all]\n    \n    Examples:\n    !list-coupons       # Show active only\n    !list-coupons all   # Show all including inactive\n    """
        show_inactive = show_all and show_all.lower() == 'all'
        def get_coupons():
            return get_all_coupons(active_only=not show_inactive)
        coupons = await run_in_executor(get_coupons)
        if not coupons:
            await ctx.send(embed=create_error_embed('No Coupons', 'No coupon codes exist. Create one with `{PREFIX}create-coupon`.'))
            return
        else:
            embed = create_info_embed('💳 Coupon Codes (Admin View)', f"{('All coupon codes' if show_inactive else 'Active coupon codes only')}")
            for coupon in coupons[:25]:
                status = '✅ Active' if coupon['active'] else '❌ Disabled'
                if coupon['expires_at']:
                    expiry_dt = datetime.fromisoformat(coupon['expires_at'])
                    if datetime.now() > expiry_dt:
                        expiry_text = f"❌ Expired ({expiry_dt.strftime('%Y-%m-%d')})"
                    else:
                        days_left = (expiry_dt - datetime.now()).days
                        expiry_text = f'⏰ {days_left} days left'
                else:
                    expiry_text = '♾️ Never expires'
                if coupon['max_uses']:
                    remaining = coupon['max_uses'] - coupon['current_uses']
                    usage_text = f"{coupon['current_uses']}/{coupon['max_uses']} used ({remaining} left)"
                else:
                    usage_text = f"{coupon['current_uses']} used (unlimited)"
                coupon_info = f"**ID:** {coupon['id']} | **Status:** {status}\n**Coins:** {coupon['coins']:,}\n**Usage:** {usage_text}\n**Expiry:** {expiry_text}\n**Commands:**\n`{PREFIX}coupon-stats {coupon['id']}` - View stats\n`{PREFIX}disable-coupon {coupon['id']}` - Disable\n`{PREFIX}delete-coupon {coupon['id']}` - Delete"
                add_field(embed, f"💳 {coupon['code']}", coupon_info, True)
            if len(coupons) > 25:
                embed.set_footer(text=f'Showing 25 of {len(coupons)} coupons')
            add_field(embed, '💡 Management', f'**Create:** `{PREFIX}create-coupon <coins> <code> [max_uses] [days]`\n**Stats:** `{PREFIX}coupon-stats <id>`\n**Disable:** `{PREFIX}disable-coupon <id>`\n**Enable:** `{PREFIX}enable-coupon <id>`\n**Delete:** `{PREFIX}delete-coupon <id>`', False)
            await ctx.send(embed=embed)
    @bot.command(name='coupon-stats', aliases=['coupon-info'])
    @is_admin()
    async def coupon_stats_command(ctx, coupon_id: int):
        """View detailed coupon statistics\n    \n    Usage: !coupon-stats <coupon_id>\n    """
        def get_stats():
            return get_coupon_stats(coupon_id)
        stats = await run_in_executor(get_stats)
        if not stats:
            await ctx.send(embed=create_error_embed('Coupon Not Found', f'Coupon ID #{coupon_id} not found.'))
            return
        else:
            coupon = stats['coupon']
            status = '✅ Active' if coupon['active'] else '❌ Disabled'
            if coupon['expires_at']:
                expiry_dt = datetime.fromisoformat(coupon['expires_at'])
                if datetime.now() > expiry_dt:
                    expiry_text = f"❌ Expired on {expiry_dt.strftime('%Y-%m-%d %H:%M')}"
                else:
                    days_left = (expiry_dt - datetime.now()).days
                    expiry_text = f"⏰ Expires in {days_left} days ({expiry_dt.strftime('%Y-%m-%d')})"
            else:
                expiry_text = '♾️ Never expires'
            if coupon['max_uses']:
                remaining = coupon['max_uses'] - coupon['current_uses']
                usage_pct = coupon['current_uses'] / coupon['max_uses'] * 100
                usage_text = f"{coupon['current_uses']}/{coupon['max_uses']} ({usage_pct:.1f}%)\n{remaining} uses remaining"
            else:
                usage_text = f"{coupon['current_uses']} times\nUnlimited uses"
            embed = create_info_embed(f"💳 Coupon: {coupon['code']}", f'Detailed statistics for coupon #{coupon_id}')
            add_field(embed, '📊 Basic Info', f"**Code:** `{coupon['code']}`\n**Status:** {status}\n**Coins:** {coupon['coins']:,}\n**Created:** {datetime.fromisoformat(coupon['created_at']).strftime('%Y-%m-%d %H:%M')}", True)
            add_field(embed, '📈 Usage Stats', f"**Times Used:** {usage_text}\n**Total Coins Given:** {stats['total_coins']:,}\n**Unique Users:** {stats['redemptions']}", True)
            add_field(embed, '⏰ Expiry', expiry_text, True)
            if stats['recent']:
                recent_text = []
                for redemption in stats['recent'][:5]:
                    user_id = redemption['user_id']
                    coins = redemption['coins_received']
                    date = datetime.fromisoformat(redemption['redeemed_at']).strftime('%Y-%m-%d %H:%M')
                    recent_text.append(f'• <@{user_id}>: {coins:,} coins ({date})')
                add_field(embed, '🕐 Recent Redemptions', '\n'.join(recent_text), False)
            else:
                add_field(embed, '🕐 Recent Redemptions', 'No redemptions yet', False)
            add_field(embed, '💡 Management', f'`{PREFIX}disable-coupon {coupon_id}` - Disable coupon\n`{PREFIX}enable-coupon {coupon_id}` - Enable coupon\n`{PREFIX}delete-coupon {coupon_id}` - Delete permanently', False)
            await ctx.send(embed=embed)
    @bot.command(name='disable-coupon', aliases=['deactivate-coupon'])
    @is_admin()
    async def disable_coupon_command(ctx, coupon_id: int):
        # irreducible cflow, using cdg fallback
        """Disable a coupon code\n    \n    Usage: !disable-coupon <coupon_id>\n    """
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT * FROM coupon_codes WHERE id = ?', (coupon_id,))
        coupon = cur.fetchone()
        if not coupon:
            conn.close()
            await ctx.send(embed=create_error_embed('Coupon Not Found', f'Coupon ID #{coupon_id} not found.'))
                return
            coupon = dict(coupon)
            cur.execute('UPDATE coupon_codes SET active = 0 WHERE id = ?', (coupon_id,))
            conn.commit()
            conn.close()
            embed = create_success_embed('✅ Coupon Disabled', f"**Code:** `{coupon['code']}`\n**Coupon ID:** {coupon_id}\n\nThis coupon can no longer be redeemed.\nUse `{PREFIX}enable-coupon {coupon_id}` to re-enable it.")
            await ctx.send(embed=embed)
            logger.info(f"Admin {ctx.author.name} disabled coupon {coupon['code']}")
            except Exception as e:
                    await ctx.send(embed=create_error_embed('Failed', f'Error: {str(e)}'))
                    logger.error(f'Failed to disable coupon: {e}')
    @bot.command(name='enable-coupon', aliases=['activate-coupon'])
    @is_admin()
    async def enable_coupon_command(ctx, coupon_id: int):
        # irreducible cflow, using cdg fallback
        """Enable a disabled coupon code\n    \n    Usage: !enable-coupon <coupon_id>\n    """
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT * FROM coupon_codes WHERE id = ?', (coupon_id,))
        coupon = cur.fetchone()
        if not coupon:
            conn.close()
            await ctx.send(embed=create_error_embed('Coupon Not Found', f'Coupon ID #{coupon_id} not found.'))
                return
            coupon = dict(coupon)
            cur.execute('UPDATE coupon_codes SET active = 1 WHERE id = ?', (coupon_id,))
            conn.commit()
            conn.close()
            embed = create_success_embed('✅ Coupon Enabled', f"**Code:** `{coupon['code']}`\n**Coupon ID:** {coupon_id}\n\nThis coupon can now be redeemed again.\nUsers can use: `{PREFIX}redeem {coupon['code']}`")
            await ctx.send(embed=embed)
            logger.info(f"Admin {ctx.author.name} enabled coupon {coupon['code']}")
            except Exception as e:
                    await ctx.send(embed=create_error_embed('Failed', f'Error: {str(e)}'))
                    logger.error(f'Failed to enable coupon: {e}')
    @bot.command(name='delete-coupon', aliases=['remove-coupon'])
    @is_admin()
    async def delete_coupon_command(ctx, coupon_id: int):
        # irreducible cflow, using cdg fallback
        """Delete a coupon code permanently\n    \n    Usage: !delete-coupon <coupon_id>\n    """
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT * FROM coupon_codes WHERE id = ?', (coupon_id,))
        coupon = cur.fetchone()
        if not coupon:
            conn.close()
            await ctx.send(embed=create_error_embed('Coupon Not Found', f'Coupon ID #{coupon_id} not found.'))
                return
            coupon = dict(coupon)
            cur.execute('SELECT COUNT(*) as count FROM coupon_redemptions WHERE coupon_id = ?', (coupon_id,))
            redemptions = cur.fetchone()['count']
            cur.execute('DELETE FROM coupon_codes WHERE id = ?', (coupon_id,))
            conn.commit()
            conn.close()
            embed = create_success_embed('✅ Coupon Deleted', f"**Code:** `{coupon['code']}`\n**Coupon ID:** {coupon_id}\n**Total Redemptions:** {redemptions}\n\nThis coupon has been permanently deleted.\nRedemption history has been preserved.")
            await ctx.send(embed=embed)
            logger.info(f"Admin {ctx.author.name} deleted coupon {coupon['code']}")
            except Exception as e:
                    await ctx.send(embed=create_error_embed('Failed', f'Error: {str(e)}'))
                    logger.error(f'Failed to delete coupon: {e}')
                        return
    @bot.command(name='security-logs', aliases=['sec-logs', 'suspicious'])
    @is_admin()
    async def security_logs_command(ctx, user: discord.Member=None, limit: int=20):
        # irreducible cflow, using cdg fallback
        """View security logs and suspicious activity\n    \n    Usage: !security-logs [@user] [limit]\n    \n    Examples:\n    !security-logs              # Show recent 20 logs\n    !security-logs @user        # Show logs for specific user\n    !security-logs @user 50     # Show 50 logs for user\n    """
        conn = get_db()
        cur = conn.cursor()
        if user:
            cur.execute('SELECT * FROM security_logs \n                           WHERE user_id = ? \n                           ORDER BY created_at DESC LIMIT ?', (str(user.id), limit))
        else:
            cur.execute('SELECT * FROM security_logs \n                           ORDER BY created_at DESC LIMIT ?', (limit,))
        logs = [dict(row) for row in cur.fetchall()]
        conn.close()
        if not logs:
            await ctx.send(embed=create_info_embed('🔒 Security Logs', 'No security events found.'))
                return
            embed = create_info_embed('🔒 Security Logs', f'Showing {len(logs)} most recent security events')
            for log in logs[:10]:
                severity_emoji = {'low': '🟢', 'medium': '🟡', 'high': '🔴', 'critical': '🚨'}.get(log['severity'], '⚪')
                flag_emoji = '🚩' if log['flagged'] else ''
                log_text = f"{severity_emoji} **{log['activity_type']}** {flag_emoji}\nUser: <@{log['user_id']}>\n{log['description']}\nTime: {datetime.fromisoformat(log['created_at']).strftime('%Y-%m-%d %H:%M')}"
                add_field(embed, f"Log #{log['id']}", log_text, False)
            if len(logs) > 10:
                embed.set_footer(text=f'Showing 10 of {len(logs)} logs')
            await ctx.send(embed=embed)
            except Exception as e:
                    await ctx.send(embed=create_error_embed('Failed', f'Error: {str(e)}'))
                    logger.error(f'Failed to get security logs: {e}')
    @bot.command(name='trust-score', aliases=['trust', 'user-trust'])
    @is_admin()
    async def trust_score_command(ctx, user: discord.Member):
        # irreducible cflow, using cdg fallback
        """View user\'s trust score and security status\n    \n    Usage: !trust-score @user\n    """
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute('SELECT * FROM user_trust WHERE user_id = ?', (str(user.id),))
            trust = cur.fetchone()
            if not trust:
                cur.execute('INSERT INTO user_trust (user_id, trust_score, warnings, violations)\n                           VALUES (?, 100, 0, 0)', (str(user.id),))
                conn.commit()
                trust_score = 100
                warnings = 0
                violations = 0
                restricted = False
                notes = None
            else:
                trust = dict(trust)
                trust_score = trust['trust_score']
                warnings = trust['warnings']
                violations = trust['violations']
                restricted = trust['restricted'] == 1
                notes = trust.get('notes')
            cur.execute('SELECT COUNT(*) as count FROM security_logs \n                       WHERE user_id = ? AND severity IN (\'high\', \'critical\')', (str(user.id),))
            high_severity_count = cur.fetchone()['count']
            conn.close()
            if trust_score >= 80:
                color = 3066993
                status = '✅ Trusted'
            else:
                if trust_score >= 50:
                    color = 15965202
                    status = '⚠️ Caution'
                else:
                    if trust_score >= 20:
                        color = 15158332
                        status = '🔴 Warning'
                    else:
                        color = 9807270
                        status = '🚫 High Risk'
            embed = create_embed(f'🔒 Trust Score: {user.name}', status, color)
            add_field(embed, '📊 Trust Score', f'**{trust_score}/100**', True)
            add_field(embed, '⚠️ Warnings', str(warnings), True)
            add_field(embed, '❌ Violations', str(violations), True)
            add_field(embed, '🚨 High Severity Events', str(high_severity_count), True)
            add_field(embed, '🔒 Restricted', 'Yes' if restricted else 'No', True)
            if notes:
                add_field(embed, '📝 Notes', notes[(-500):], False)
            add_field(embed, '💡 Actions', f'`{PREFIX}restrict-user @user` - Restrict from earning coins\n`{PREFIX}unrestrict-user @user` - Remove restriction\n`{PREFIX}reset-trust @user` - Reset trust score to 100\n`{PREFIX}security-logs @user` - View security logs', False)
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=create_error_embed('Failed', f'Error: {str(e)}'))
            logger.error(f'Failed to get trust score: {e}')
            return
    @bot.command(name='restrict-user', aliases=['restrict'])
    @is_admin()
    async def restrict_user_command(ctx, user: discord.Member, *, reason: str='Admin action'):
        # irreducible cflow, using cdg fallback
        """Restrict user from earning coins\n    \n    Usage: !restrict-user @user [reason]\n    """
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute('INSERT OR IGNORE INTO user_trust \n                       (user_id, trust_score, warnings, violations)\n                       VALUES (?, 100, 0, 0)', (str(user.id),))
            cur.execute('UPDATE user_trust \n                       SET restricted = 1,\n                           notes = COALESCE(notes || \'\n\', \'\') || ?\n                       WHERE user_id = ?', (f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] RESTRICTED: {reason}", str(user.id)))
            conn.commit()
            conn.close()
            log_security_event(str(user.id), 'admin_restriction', f'Restricted by {ctx.author.name}: {reason}', 'high')
            embed = create_success_embed('🔒 User Restricted', f'**User:** {user.mention}\n**Reason:** {reason}\n\nThis user can no longer earn coins through any method.\nUse `{PREFIX}unrestrict-user @user` to remove restriction.')
            await ctx.send(embed=embed)
            try:
                user_embed = create_error_embed('🔒 Account Restricted', f'Your account has been restricted from earning coins.\n\n**Reason:** {reason}\n\nContact an administrator for more information.')
                await user.send(embed=user_embed)
            except:
                pass
            logger.info(f'Admin {ctx.author.name} restricted user {user.name}: {reason}')
        except Exception as e:
            await ctx.send(embed=create_error_embed('Failed', f'Error: {str(e)}'))
            logger.error(f'Failed to restrict user: {e}')
            return
    @bot.command(name='unrestrict-user', aliases=['unrestrict'])
    @is_admin()
    async def unrestrict_user_command(ctx, user: discord.Member):
        # irreducible cflow, using cdg fallback
        """Remove restriction from user\n    \n    Usage: !unrestrict-user @user\n    """
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute('UPDATE user_trust \n                       SET restricted = 0,\n                           notes = COALESCE(notes || \'\n\', \'\') || ?\n                       WHERE user_id = ?', (f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] UNRESTRICTED by {ctx.author.name}", str(user.id)))
            conn.commit()
            conn.close()
            embed = create_success_embed('✅ Restriction Removed', f'**User:** {user.mention}\n\nThis user can now earn coins again.')
            await ctx.send(embed=embed)
            try:
                user_embed = create_success_embed('✅ Restriction Removed', 'Your account restriction has been lifted.\nYou can now earn coins again!')
                await user.send(embed=user_embed)
            except:
                pass
            logger.info(f'Admin {ctx.author.name} unrestricted user {user.name}')
        except Exception as e:
            await ctx.send(embed=create_error_embed('Failed', f'Error: {str(e)}'))
            logger.error(f'Failed to unrestrict user: {e}')
            return
    @bot.command(name='reset-trust', aliases=['reset-trust-score'])
    @is_admin()
    async def reset_trust_command(ctx, user: discord.Member):
        # irreducible cflow, using cdg fallback
        """Reset user\'s trust score to 100\n    \n    Usage: !reset-trust @user\n    """
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute('UPDATE user_trust \n                       SET trust_score = 100,\n                           warnings = 0,\n                           violations = 0,\n                           notes = COALESCE(notes || \'\n\', \'\') || ?\n                       WHERE user_id = ?', (f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Trust score reset by {ctx.author.name}", str(user.id)))
            conn.commit()
            conn.close()
            embed = create_success_embed('✅ Trust Score Reset', f'**User:** {user.mention}\n**New Score:** 100/100\n\nWarnings and violations have been cleared.')
            await ctx.send(embed=embed)
            logger.info(f'Admin {ctx.author.name} reset trust score for {user.name}')
        except Exception as e:
            await ctx.send(embed=create_error_embed('Failed', f'Error: {str(e)}'))
            logger.error(f'Failed to reset trust: {e}')
    @bot.command(name='coinhelp', aliases=['earncoins', 'howtocoins'])
    async def coin_help(ctx):
        """Show how to earn coins"""
        coins_per_invite = int(get_setting('coins_per_invite', 50))
        coins_per_message = int(get_setting('coins_per_message', 1))
        coins_per_voice_min = int(get_setting('coins_per_voice_minute', 2))
        coins_daily = int(get_setting('coins_daily_reward', 100))
        message_cooldown = int(get_setting('message_cooldown_seconds', 60))
        voice_min_duration = int(get_setting('voice_min_duration_minutes', 5))
        embed = create_embed('💰 How to Earn Coins', 'All the ways to earn coins!', 15844367)
        add_field(embed, '🎁 Daily Reward', f'**{coins_daily} coins** per day\nCommand: `{PREFIX}daily`\nClaim once every 24 hours!', False)
        add_field(embed, '👥 Invite Members', f'**{coins_per_invite} coins** per invite\nInvite friends to the server!\nAutomatic reward when they join', False)
        add_field(embed, '💬 Send Messages', f'**{coins_per_message} coin** per message\nCooldown: {message_cooldown} seconds\nChat actively to earn!', False)
        add_field(embed, '🎤 Voice Activity', f'**{coins_per_voice_min} coins** per minute\nMinimum: {voice_min_duration} minutes\nJoin voice channels!', False)
        add_field(embed, '� Redeem Coupons', f'**Redeem coupon codes** for instant coins!\nCommand: `{PREFIX}redeem <code>`\nWatch for codes in announcements!', False)
        add_field(embed, '� Coin Uses', f'• Renew VPS: `{PREFIX}renew <vps#> <days>`\n• Deploy VPS: `{PREFIX}deploy <plan_id>`\n• Upgrade VPS: `{PREFIX}upgrade <vps#> <plan_id>`\n• Shop items: `{PREFIX}shop`', False)
        add_field(embed, '📊 Check Your Stats', f'`{PREFIX}balance` - Check your coins\n`{PREFIX}leaderboard` - See top earners\n`{PREFIX}transactions` - View history', False)
        await ctx.send(embed=embed)
    @bot.command(name='givecoins')
    @is_admin()
    async def give_coins(ctx, user: discord.Member, amount: int, *, reason: str='Admin gift'):
        """Give coins to a user (Admin only)"""
        if amount <= 0:
            await ctx.send(embed=create_error_embed('Invalid Amount', 'Amount must be positive.'))
            return
        else:
            user_id = str(user.id)
            new_balance = await run_in_executor(add_coins, user_id, amount, 'admin_give', reason)
            embed = create_success_embed('💰 Coins Given', f'Gave **{amount:,} coins** to {user.mention}\nReason: {reason}\nTheir new balance: **{new_balance:,} coins**')
            await ctx.send(embed=embed)
            try:
                dm_embed = create_success_embed('🎁 You Received Coins!', f'An admin gave you **{amount:,} coins**!\nReason: {reason}\nNew balance: **{new_balance:,} coins**')
                await user.send(embed=dm_embed)
            except:
                return None
    @bot.command(name='removecoins', aliases=['takecoins'])
    @is_admin()
    async def remove_coins_command(ctx, user: discord.Member, amount: int, *, reason: str='Admin removal'):
        """Remove coins from a user (Admin only)"""
        if amount <= 0:
            await ctx.send(embed=create_error_embed('Invalid Amount', 'Amount must be positive.'))
            return
        else:
            user_id = str(user.id)
            success, new_balance = await run_in_executor(remove_coins, user_id, amount, 'admin_remove', reason)
            if not success:
                await ctx.send(embed=create_error_embed('Insufficient Coins', f'{user.mention} only has **{new_balance:,} coins**.'))
                return
            else:
                embed = create_success_embed('💸 Coins Removed', f'Removed **{amount:,} coins** from {user.mention}\nReason: {reason}\nTheir new balance: **{new_balance:,} coins**')
                await ctx.send(embed=embed)
                try:
                    dm_embed = create_warning_embed('⚠️ Coins Removed', f'An admin removed **{amount:,} coins** from your account.\nReason: {reason}\nNew balance: **{new_balance:,} coins**')
                    await user.send(embed=dm_embed)
                except:
                    return None
    @bot.command(name='setcoins')
    @is_admin()
    async def set_coins_command(ctx, user: discord.Member, amount: int):
        """Set a user\'s coin balance (Admin only)"""
        if amount < 0:
            await ctx.send(embed=create_error_embed('Invalid Amount', 'Amount cannot be negative.'))
            return
        else:
            user_id = str(user.id)
            def set_balance():
                coins_data = get_user_coins(user_id)
                current_balance = coins_data['balance']
                diff = amount - current_balance
                if diff > 0:
                    add_coins(user_id, diff, 'admin_set', f'Balance set to {amount}')
                    return (current_balance, diff)
                else:
                    if diff < 0:
                        remove_coins(user_id, abs(diff), 'admin_set', f'Balance set to {amount}')
                    return (current_balance, diff)
            current_balance, diff = await run_in_executor(set_balance)
            embed = create_success_embed('💰 Balance Set', f'Set {user.mention}\'s balance to **{amount:,} coins**\nPrevious balance: **{current_balance:,} coins**\nChange: **{diff:+,} coins**')
            await ctx.send(embed=embed)
    @bot.command(name='coinconfig', aliases=['coinsettings'])
    @is_admin()
    async def coin_config(ctx, setting: str=None, value: str=None):
        """Configure coin economy settings (Admin only)"""
        if setting is None:
            embed = create_info_embed('⚙️ Coin Economy Settings', 'Current configuration')
            settings_to_show = [('coins_per_invite', 'Coins per Invite'), ('coins_per_message', 'Coins per Message'), ('coins_per_voice_minute', 'Coins per Voice Minute'), ('coins_daily_reward', 'Daily Reward'), ('coins_vps_renewal_1day', 'VPS Renewal (1 day)'), ('coins_vps_renewal_7days', 'VPS Renewal (7 days)'), ('coins_vps_renewal_30days', 'VPS Renewal (30 days)'), ('default_vps_duration_days', 'Default VPS Duration'), ('vps_expiry_warning_hours', 'Expiry Warning (hours)'), ('message_cooldown_seconds', 'Message Cooldown (sec)'), ('voice_min_duration_minutes', 'Min Voice Duration (min)')]
            config_text = []
            for key, label in settings_to_show:
                val = get_setting(key, 'Not set')
                config_text.append(f'**{label}:** `{val}`')
            add_field(embed, 'Current Settings', '\n'.join(config_text), False)
            add_field(embed, 'Usage', f'`{PREFIX}coinconfig <setting> <value>`\nExample: `{PREFIX}coinconfig coins_per_invite 100`', False)
            await ctx.send(embed=embed)
        else:
            if value is None:
                await ctx.send(embed=create_error_embed('Missing Value', f'Usage: `{PREFIX}coinconfig <setting> <value>`'))
            else:
                try:
                    int(value)
                    set_setting(setting, value)
                    embed = create_success_embed('✅ Setting Updated', f'**{setting}** = `{value}`\n\nThe new value will take effect immediately.')
                    await ctx.send(embed=embed)
                except ValueError:
                    await ctx.send(embed=create_error_embed('Invalid Value', 'Value must be a number.'))
    @bot.command(name='achievements', aliases=['ach', 'badges'])
    async def achievements_command(ctx, user: discord.Member=None):
        """View achievements"""
        target_user = user or ctx.author
        user_id = str(target_user.id)
        def get_achievements_data():
            unlocked = get_user_achievements(user_id)
            conn = get_db()
            cur = conn.cursor()
            cur.execute('SELECT * FROM achievements ORDER BY category, reward_coins')
            all_achievements = [dict(row) for row in cur.fetchall()]
            conn.close()
            return (unlocked, all_achievements)
        unlocked, all_achievements = await run_in_executor(get_achievements_data)
        unlocked_ids = [a['id'] for a in unlocked]
        embed = create_embed('🏆 Achievements', f'Progress for {target_user.mention}', 15844367)
        add_field(embed, '📊 Progress', f'**Unlocked:** {len(unlocked)}/{len(all_achievements)}\n**Completion:** {int(len(unlocked) / len(all_achievements) * 100)}%', True)
        categories = {}
        for ach in all_achievements:
            cat = ach['category']
            if cat not in categories:
                categories[cat] = []
            status = '✅' if ach['id'] in unlocked_ids else '🔒'
            categories[cat].append(f"{status} {ach['icon']} **{ach['name']}** - {ach['reward_coins']} coins")
        for cat, achs in categories.items():
            add_field(embed, f'📁 {cat.title()}', '\n'.join(achs[:5]), False)
            if len(achs) > 5:
                add_field(embed, '...', f'And {len(achs) - 5} more', False)
        await ctx.send(embed=embed)
    @bot.command(name='quests', aliases=['quest', 'missions'])
    async def quests_command(ctx):
        """View active quests"""
        user_id = str(ctx.author.id)
        def get_quests_data():
            daily_quests = get_active_quests(user_id, 'daily')
            weekly_quests = get_active_quests(user_id, 'weekly')
            return (daily_quests, weekly_quests)
        daily_quests, weekly_quests = await run_in_executor(get_quests_data)
        embed = create_embed('📜 Active Quests', 'Complete quests to earn bonus coins!', 10181046)
        if daily_quests:
            daily_text = []
            for quest in daily_quests:
                progress = quest.get('progress', 0)
                required = quest['requirement_value']
                reward = quest['reward_coins']
                completed = quest.get('completed', 0)
                if completed:
                    status = '✅'
                    bar = '██████████'
                else:
                    status = '🔄'
                    pct = min(progress / required, 1.0)
                    filled = int(pct * 10)
                    bar = '█' * filled + '░' * (10 - filled)
                daily_text.append(f"{status} **{quest['name']}**\n   {bar} {progress}/{required}\n   Reward: {reward} coins")
            add_field(embed, '📅 Daily Quests', '\n\n'.join(daily_text), False)
        if weekly_quests:
            weekly_text = []
            for quest in weekly_quests:
                progress = quest.get('progress', 0)
                required = quest['requirement_value']
                reward = quest['reward_coins']
                completed = quest.get('completed', 0)
                if completed:
                    status = '✅'
                    bar = '██████████'
                else:
                    status = '🔄'
                    pct = min(progress / required, 1.0)
                    filled = int(pct * 10)
                    bar = '█' * filled + '░' * (10 - filled)
                weekly_text.append(f"{status} **{quest['name']}**\n   {bar} {progress}/{required}\n   Reward: {reward} coins")
            add_field(embed, '📆 Weekly Quests', '\n\n'.join(weekly_text), False)
        await ctx.send(embed=embed)
    @bot.command(name='redeem', aliases=['coupon', 'code'])
    async def redeem_coupon_command(ctx, code: str=None):
        """Redeem a coupon code for coins"""
        user_id = str(ctx.author.id)
        if not code:
            embed = create_info_embed('💳 Redeem Coupon', f'Enter a coupon code to receive coins!\n\n**Usage:** `{PREFIX}redeem <code>`\n**Example:** `{PREFIX}redeem WELCOME2024`\n\n**Where to get codes:**\n• Server events and giveaways\n• Social media promotions\n• Special announcements\n• Community rewards\n\n💡 Codes are case-insensitive')
            await ctx.send(embed=embed)
            return
        else:
            def redeem():
                return redeem_coupon(code, user_id)
            success, message, coins = await run_in_executor(redeem)
            if success:
                def get_balance():
                    return get_user_coins(user_id)['balance']
                new_balance = await run_in_executor(get_balance)
                embed = create_success_embed('🎉 Coupon Redeemed!', f'You\'ve successfully redeemed the coupon!\n\n**Code:** `{code.upper()}`\n**Coins Received:** +{coins:,} coins\n**New Balance:** {new_balance:,} coins\n\n💰 Enjoy your coins!')
                await ctx.send(embed=embed)
                logger.info(f'User {ctx.author.name} redeemed coupon {code} for {coins} coins')
            else:
                embed = create_error_embed('❌ Redemption Failed', f'{message}\n\n**Code Entered:** `{code.upper()}`\n\n**Common Issues:**\n• Code already used by you\n• Code has expired\n• Code has reached usage limit\n• Invalid or disabled code\n\n💡 Check for typos and try again!')
                await ctx.send(embed=embed)
    @bot.command(name='shop', aliases=['store', 'buy'])
    async def shop_command(ctx, item_id: int=None):
        """View or purchase from the coin shop"""
        user_id = str(ctx.author.id)
        if item_id is None:
            def get_shop_data():
                items = get_shop_items()
                coins_data = get_user_coins(user_id)
                return (items, coins_data)
            items, coins_data = await run_in_executor(get_shop_data)
            embed = create_embed('🛒 Coin Shop', 'Purchase items with your coins!', 15158332)
            types = {}
            for item in items:
                t = item['item_type']
                if t not in types:
                    types[t] = []
                types[t].append(item)
            for item_type, type_items in types.items():
                items_text = []
                for item in type_items[:5]:
                    stock_text = f" (Stock: {item['stock']})" if item['stock']!= (-1) else ''
                    items_text.append(f"{item['icon']} **[{item['id']}]** {item['name']}{stock_text}\n   {item['description']}\n   Price: **{item['price']:,} coins**")
                add_field(embed, f"📦 {item_type.replace('_', ' ').title()}", '\n\n'.join(items_text), False)
            add_field(embed, '💰 Your Balance', f"{coins_data['balance']:,} coins", False)
            add_field(embed, '💡 How to Buy', f'Use `{PREFIX}shop <item_id>` to purchase', False)
            await ctx.send(embed=embed)
        else:
            def process_purchase():
                success, message, item = purchase_item(user_id, item_id)
                if success:
                    coins_data = get_user_coins(user_id)
                    return (success, message, item, coins_data)
                else:
                    return (success, message, item, None)
            success, message, item, coins_data = await run_in_executor(process_purchase)
            if not success:
                await ctx.send(embed=create_error_embed('Purchase Failed', message))
                return
            else:
                item_data = json.loads(item['item_data']) if item['item_data'] else {}
                if item['item_type'] == 'booster':
                    multiplier = item_data.get('multiplier', 2.0)
                    duration = item_data.get('duration', 3600)
                    await run_in_executor(activate_booster, user_id, multiplier, duration)
                    hours = duration // 3600
                    effect_msg = f'**{multiplier}x** coin earnings for **{hours} hour(s)**!'
                else:
                    if item['item_type'] == 'vps_extension':
                        days = item_data.get('days', 3)
                        effect_msg = f'VPS extended by **{days} days**! Use `{PREFIX}myvps` to see.'
                    else:
                        effect_msg = 'Item purchased! Check your inventory.'
                embed = create_success_embed('✅ Purchase Successful!', f"You bought: **{item['name']}**\n\n{effect_msg}\n\n**New Balance:** {coins_data['balance']:,} coins")
                await ctx.send(embed=embed)
    @bot.command(name='work', aliases=['job'])
    async def work_command(ctx):
        """Work to earn coins - Non-blocking version"""
        user_id = str(ctx.author.id)
        if is_user_restricted(user_id):
            await ctx.send(embed=create_error_embed('❌ Access Restricted', 'Your account has been restricted from earning coins due to suspicious activity.\nContact an administrator for more information.'))
            return
        else:
            allowed, remaining = check_rate_limit(user_id, 'work_attempt', 7, 60)
            if not allowed:
                log_security_event(user_id, 'work_spam', 'Excessive work command attempts', 'medium')
                await ctx.send(embed=create_error_embed('⏰ Slow Down', f'You\'re trying to work too frequently. Please wait {remaining}s before trying again.'))
                return
            else:
                def do_work():
                    try:
                        success, earnings, message = work_for_coins(user_id)
                        if not success:
                            return (False, None, message, None)
                        else:
                            coins_data = get_user_coins(user_id)
                            conn = get_db()
                            cur = conn.cursor()
                            cur.execute('SELECT * FROM user_jobs WHERE user_id = ?', (user_id,))
                            job_row = cur.fetchone()
                            job_data = dict(job_row) if job_row else None
                            conn.close()
                            return (True, coins_data, message, job_data)
                    except Exception as e:
                        logger.error(f'Error in work command: {e}')
                        return (False, None, f'Error: {str(e)}', None)
                success, coins_data, message, job_data = await run_in_executor(do_work)
                if not success:
                    embed = create_warning_embed('⏰ Work Cooldown', message)
                    await ctx.send(embed=embed)
                    return
                else:
                    embed = create_success_embed('⚒️ Work Complete!', message)
                    if job_data:
                        add_field(embed, '💼 Job', f"{job_data['current_job']} (Level {job_data['job_level']})", True)
                        add_field(embed, '📊 Experience', f"{job_data['job_experience']}/{job_data['job_level'] * 100}", True)
                    add_field(embed, '💰 New Balance', f"{coins_data['balance']:,} coins", True)
                    add_field(embed, '⏰ Next Work', 'Available in 4 hours', False)
                    await ctx.send(embed=embed)
    @bot.command(name='gift', aliases=['givecoin', 'sendcoins'])
    async def gift_command(ctx, user: discord.Member, amount: int, *, message: str=None):
        """Gift coins to another user"""
        sender_id = str(ctx.author.id)
        receiver_id = str(user.id)
        if amount <= 0:
            await ctx.send(embed=create_error_embed('Invalid Amount', 'Amount must be positive.'))
            return
        else:
            async def process_gift():
                success, result_message = gift_coins(sender_id, receiver_id, amount, message)
                if success:
                    sender_coins = get_user_coins(sender_id)
                    return (success, result_message, sender_coins)
                else:
                    return (success, result_message, None)
            success, result_message, sender_coins = await run_in_executor(process_gift)
            if not success:
                await ctx.send(embed=create_error_embed('Gift Failed', result_message))
                return
            else:
                embed = create_success_embed('🎁 Coins Gifted!', f"You sent **{amount:,} coins** to {user.mention}!\nYour new balance: **{sender_coins['balance']:,} coins**")
                if message:
                    add_field(embed, '💌 Message', message, False)
                await ctx.send(embed=embed)
                try:
                    receiver_embed = create_success_embed('🎁 You Received Coins!', f'{ctx.author.mention} sent you **{amount:,} coins**!')
                    if message:
                        add_field(receiver_embed, '💌 Message', message, False)
                    await user.send(embed=receiver_embed)
                except:
                    return None
    @bot.command(name='streak', aliases=['streaks'])
    async def streak_command(ctx, user: discord.Member=None):
        """View daily streak"""
        target_user = user or ctx.author
        user_id = str(target_user.id)
        def get_streak_data():
            conn = get_db()
            cur = conn.cursor()
            cur.execute('SELECT * FROM user_streaks WHERE user_id = ?', (user_id,))
            row = cur.fetchone()
            conn.close()
            return dict(row) if row else None
        streak_data = await run_in_executor(get_streak_data)
        if not streak_data:
            embed = create_info_embed('🔥 Daily Streak', f'{target_user.mention} hasn\'t started a streak yet!\nUse `{PREFIX}daily` to start your streak!')
            await ctx.send(embed=embed)
            return
        else:
            streak_data = dict(row)
            embed = create_embed('🔥 Daily Streak', f'Streak info for {target_user.mention}', 16739179)
            add_field(embed, '🔥 Current Streak', f"**{streak_data['current_streak']} days**", True)
            add_field(embed, '⭐ Longest Streak', f"**{streak_data['longest_streak']} days**", True)
            add_field(embed, '💰 Bonus Multiplier', f"**{streak_data['streak_bonus_multiplier']:.1f}x**", True)
            milestones = [7, 14, 30, 60, 100, 365]
            next_milestone = next((m for m in milestones if m > streak_data['current_streak']), None)
            if next_milestone:
                days_to_milestone = next_milestone - streak_data['current_streak']
                add_field(embed, '🎯 Next Milestone', f'{next_milestone} days (in {days_to_milestone} days)', False)
            add_field(embed, '💡 Tip', f'Claim `{PREFIX}daily` every day to maintain your streak!\nHigher streaks = bigger bonuses!', False)
            await ctx.send(embed=embed)
    @bot.command(name='booster', aliases=['boosters', 'boost'])
    async def booster_command(ctx):
        """View active boosters"""
        user_id = str(ctx.author.id)
        booster = await run_in_executor(get_active_booster, user_id)
        if not booster:
            embed = create_info_embed('⚡ No Active Booster', f'You don\'t have any active boosters.\n\nPurchase boosters from the shop:\n`{PREFIX}shop`')
            await ctx.send(embed=embed)
            return
        else:
            expires_at = datetime.fromisoformat(booster['expires_at'])
            time_left = expires_at - datetime.now()
            hours = int(time_left.total_seconds() // 3600)
            minutes = int(time_left.total_seconds() % 3600 // 60)
            embed = create_embed('⚡ Active Booster', 'Your coin earnings are boosted!', 65416)
            add_field(embed, '🚀 Multiplier', f"**{booster['multiplier']}x** coins", True)
            add_field(embed, '⏰ Time Left', f'**{hours}h {minutes}m**', True)
            add_field(embed, '📅 Expires', expires_at.strftime('%Y-%m-%d %H:%M'), True)
            add_field(embed, '💡 Tip', 'All coin earnings are multiplied while booster is active!\nStack activities for maximum gains!', False)
            await ctx.send(embed=embed)
    @bot.command(name='profile', aliases=['me'])
    async def profile_command(ctx, user: discord.Member=None):
        """View detailed user profile"""
        target_user = user or ctx.author
        user_id = str(target_user.id)
        def get_profile_data():
            coins_data = get_user_coins(user_id)
            achievements = get_user_achievements(user_id)
            conn = get_db()
            cur = conn.cursor()
            cur.execute('SELECT current_streak FROM user_streaks WHERE user_id = ?', (user_id,))
            streak_row = cur.fetchone()
            current_streak = streak_row[0] if streak_row else 0
            cur.execute('SELECT * FROM user_jobs WHERE user_id = ?', (user_id,))
            job_row = cur.fetchone()
            job_data = dict(job_row) if job_row else None
            cur.execute('SELECT COUNT(*) + 1 FROM user_coins \n                       WHERE balance > (SELECT balance FROM user_coins WHERE user_id = ?)', (user_id,))
            rank = cur.fetchone()[0]
            conn.close()
            booster = get_active_booster(user_id)
            return (coins_data, achievements, current_streak, job_data, rank, booster)
        coins_data, achievements, current_streak, job_data, rank, booster = await run_in_executor(get_profile_data)
        vps_count = len(vps_data.get(user_id, []))
        embed = create_embed('👤 User Profile', f'Profile for {target_user.mention}', 3447003)
        add_field(embed, '💰 Balance', f"{coins_data['balance']:,} coins", True)
        add_field(embed, '🏆 Rank', f'#{rank}', True)
        add_field(embed, '🔥 Streak', f'{current_streak} days', True)
        add_field(embed, '📈 Total Earned', f"{coins_data['total_earned']:,} coins", True)
        add_field(embed, '📉 Total Spent', f"{coins_data['total_spent']:,} coins", True)
        add_field(embed, '🏅 Achievements', f'{len(achievements)}', True)
        add_field(embed, '📊 Activity Stats', f"👥 Invites: {coins_data['invite_count']}\n💬 Messages: {coins_data['message_count']}\n🎤 Voice: {coins_data['voice_minutes']} min\n🖥️ VPS: {vps_count}", True)
        if job_data:
            add_field(embed, '💼 Job', f"{job_data['current_job']}\nLevel {job_data['job_level']}\nWorked {job_data['total_work_count']} times", True)
        if booster:
            add_field(embed, '⚡ Active Booster', f"{booster['multiplier']}x earnings", True)
        await ctx.send(embed=embed)
    @bot.command(name='quickhelp')
    async def quick_help(ctx):
        """Show quick reference for common tasks"""
        user_id = str(ctx.author.id)
        is_admin_user = user_id == str(MAIN_ADMIN_ID) or user_id in admin_data.get('admins', [])
        embed = create_info_embed('🚀 Quick Help Reference', 'Quick reference for common tasks. Use `!help` for complete command list.')
        add_field(embed, '👤 For Users', '• `!myvps` - List your VPS\n• `!manage` - Start/stop/manage VPS\n• `!ports` - Manage port forwarding\n• `!share-user @user 1` - Share VPS #1\n• `!about` - Bot information', False)
        add_field(embed, '🖥️ VPS Control', '• In `!manage`: Click ▶ to start VPS\n• In `!manage`: Click ⏸ to stop VPS\n• In `!manage`: Click 🔑 for SSH access\n• In `!manage`: Click 📊 for live stats\n• In `!manage`: Click 🔄 to reinstall OS', False)
        add_field(embed, '🔧 Common Issues', '• Ports not working? Use `!repair-ports <container>` (admin)\n• VPS suspended? Contact admin to unsuspend\n• Need more resources? Contact admin for upgrade\n• SSH not working? Try reinstall with different OS', False)
        if is_admin_user:
            add_field(embed, '🛡️ Admin Quick Actions', '• `!create 2 2 20 @user` - Create 2GB/2CPU/20GB VPS\n• `!userinfo @user` - Check user details\n• `!node list` - List all nodes\n• `!serverstats` - System overview\n• `!suspend-vps <container> <reason>` - Suspend VPS', False)
        embed.set_footer(text=f'{BOT_NAME} VPS Manager • Use !help for complete command list')
        await ctx.send(embed=embed)
    @bot.command(name='help-search')
    async def help_search(ctx, *, search_term: str=None):
        """Search for commands"""
        if not search_term:
            await show_help(ctx)
            return
        else:
            search_term = search_term.lower()
            user_id = str(ctx.author.id)
            is_admin_user = user_id == str(MAIN_ADMIN_ID) or user_id in admin_data.get('admins', [])
            is_main_admin_user = user_id == str(MAIN_ADMIN_ID)
            all_commands = []
            user_categories = ['user', 'vps', 'ports', 'system', 'bot']
            for cat in user_categories:
                all_commands.extend(HelpView(ctx).command_categories[cat]['commands'])
            if is_admin_user:
                all_commands.extend(HelpView(ctx).command_categories['admin']['commands'])
                all_commands.extend(HelpView(ctx).command_categories['nodes']['commands'])
            if is_main_admin_user:
                all_commands.extend(HelpView(ctx).command_categories['main_admin']['commands'])
            matches = []
            for cmd, desc in all_commands:
                if search_term in cmd.lower() or search_term in desc.lower():
                    matches.append((cmd, desc))
            if not matches:
                embed = create_info_embed('🔍 No Results Found', f'No commands found matching \'{search_term}\'. Try a different search term.')
                await ctx.send(embed=embed)
            else:
                embed = create_info_embed(f'🔍 Search Results for \'{search_term}\'', f'Found {len(matches)} command(s) matching your search.')
                results_text = '\n'.join([f'**{cmd}** - {desc}' for cmd, desc in matches[:15]])
                add_field(embed, 'Matching Commands', results_text, False)
                if len(matches) > 15:
                    add_field(embed, 'Note', f'Showing 15 of {len(matches)} matches. Try a more specific search.', False)
                embed.set_footer(text=f'{BOT_NAME} VPS Manager • Use !help for complete list')
                await ctx.send(embed=embed)
    @bot.command(name='node')
    @is_admin()
    async def node_cmd(ctx, sub: str, *args):
        if sub == 'create':
            await ctx.send('Enter node name:')
            def check(m):
                return m.author == ctx.author and m.channel == ctx.channel
            name = (await bot.wait_for('message', check=check)).content.strip()
            await ctx.send('Enter location:')
            location = (await bot.wait_for('message', check=check)).content.strip()
            await ctx.send('Enter total VPS capacity:')
            total_vps_str = (await bot.wait_for('message', check=check)).content.strip()
            try:
                total_vps = int(total_vps_str)
            except ValueError:
                await ctx.send(embed=create_error_embed('Invalid Input', 'Total VPS must be an integer.'))
                return
            await ctx.send('Enter tags (comma separated):')
            tags_str = (await bot.wait_for('message', check=check)).content.strip()
            tags = [t.strip() for t in tags_str.split(',') if t.strip()]
            tags_json = json.dumps(tags)
            await ctx.send('Enter node URL (e.g., http://ip:port) or leave blank for local:')
            url_str = (await bot.wait_for('message', check=check)).content.strip()
            url = url_str if url_str else None
            is_local = 1 if not url else 0
            api_key = None if is_local else ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=32))
            conn = get_db()
            cur = conn.cursor()
            try:
                cur.execute('INSERT INTO nodes (name, location, total_vps, tags, api_key, url, is_local) VALUES (?, ?, ?, ?, ?, ?, ?)', (name, location, total_vps, tags_json, api_key, url, is_local))
                conn.commit()
                node_id = cur.lastrowid
                embed = create_success_embed('Node Created', f"ID: {node_id}\nName: {name}\nLocation: {location}\nCapacity: {total_vps}\nTags: {', '.join(tags)}")
                if not is_local:
                    add_field(embed, 'API Key', api_key, False)
                    add_field(embed, 'URL', url, False)
                    add_field(embed, 'Setup', f'Run `python node-agent.py --api_key={api_key} --port=PORT` on the node server.')
                await ctx.send(embed=embed)
            except sqlite3.IntegrityError:
                await ctx.send(embed=create_error_embed('Error', 'Node name already exists.'))
            conn.close()
        else:
            if sub == 'list':
                nodes = get_nodes()
                embed = create_info_embed('Nodes List', '')
                for n in nodes:
                    status = 'Local' if n['is_local'] else 'Down'
                    if not n['is_local']:
                        try:
                            response = requests.get(f"{n['url']}/api/ping", params={'api_key': n['api_key']}, timeout=5)
                            status = 'Up' if response.status_code == 200 else 'Down'
                        except:
                            pass
                    field = f"ID: {n['id']}\nName: {n['name']}\nLocation: {n['location']}\nCapacity: {n['total_vps']}\nTags: {', '.join(n['tags'])}\nStatus: {status}"
                    if not n['is_local']:
                        field += f"\nURL: {n['url']}"
                    add_field(embed, f"Node {n['id']}", field, False)
                await ctx.send(embed=embed)
            else:
                if sub == 'edit':
                    if not args:
                        await ctx.send(embed=create_error_embed('Usage', f'{PREFIX}node edit <id>'))
                        return
                    else:
                        try:
                            node_id = int(args[0])
                        except ValueError:
                            await ctx.send(embed=create_error_embed('Invalid ID', 'Node ID must be an integer.'))
                            return
                        node = get_node(node_id)
                        if not node:
                            await ctx.send(embed=create_error_embed('Not Found', 'Node not found.'))
                            return
                        else:
                            await ctx.send(f"Editing node {node['name']}. Enter new name ( . to skip):")
                            def check(m):
                                return m.author == ctx.author and m.channel == ctx.channel
                            new_name = (await bot.wait_for('message', check=check)).content.strip()
                            if new_name!= '.':
                                node['name'] = new_name
                            await ctx.send('New location ( . to skip):')
                            new_loc = (await bot.wait_for('message', check=check)).content.strip()
                            if new_loc!= '.':
                                node['location'] = new_loc
                            await ctx.send('New total VPS capacity ( . to skip):')
                            new_total = (await bot.wait_for('message', check=check)).content.strip()
                            if new_total!= '.':
                                node['total_vps'] = int(new_total)
                            await ctx.send('New tags (comma separated, . to skip):')
                            new_tags = (await bot.wait_for('message', check=check)).content.strip()
                            if new_tags!= '.':
                                node['tags'] = json.dumps([t.strip() for t in new_tags.split(',') if t.strip()])
                            if not node['is_local']:
                                await ctx.send('New URL ( . to skip):')
                                new_url = (await bot.wait_for('message', check=check)).content.strip()
                                if new_url!= '.':
                                    node['url'] = new_url
                                await ctx.send('Regenerate API key? (y/n):')
                                regen = (await bot.wait_for('message', check=check)).content.strip().lower()
                                if regen == 'y':
                                    node['api_key'] = ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=32))
                            conn = get_db()
                            cur = conn.cursor()
                            cur.execute('UPDATE nodes SET name=?, location=?, total_vps=?, tags=?, api_key=?, url=? WHERE id=?', (node['name'], node['location'], node['total_vps'], json.dumps(node['tags']), node.get('api_key'), node.get('url'), node_id))
                            conn.commit()
                            conn.close()
                            embed = create_success_embed('Node Updated', f"ID: {node_id}\nName: {node['name']}\nLocation: {node['location']}\nCapacity: {node['total_vps']}\nTags: {', '.join(node['tags'])}")
                            if not node['is_local']:
                                add_field(embed, 'API Key', node['api_key'], False)
                                add_field(embed, 'URL', node['url'], False)
                            await ctx.send(embed=embed)
                else:
                    if sub == 'delete':
                        if not args:
                            await ctx.send(embed=create_error_embed('Usage', f'{PREFIX}node delete <id> [force]'))
                            return
                        else:
                            try:
                                node_id = int(args[0])
                            except ValueError:
                                await ctx.send(embed=create_error_embed('Invalid ID', 'Node ID must be an integer.'))
                                return
                            force = False
                            if len(args) > 1 and args[1].lower() == 'force':
                                force = True
                            else:
                                if len(args) > 1:
                                    await ctx.send(embed=create_error_embed('Invalid Argument', 'Optional argument must be \'force\'.'))
                                    return
                            node = get_node(node_id)
                            if not node:
                                await ctx.send(embed=create_error_embed('Not Found', 'Node not found.'))
                                return
                            else:
                                if node['is_local']:
                                    await ctx.send(embed=create_error_embed('Cannot Delete', 'Cannot delete the local node.'))
                                    return
                                else:
                                    vps_count = get_current_vps_count(node_id)
                                    if not force and vps_count > 0:
                                        await ctx.send(embed=create_error_embed('Cannot Delete', f'Node has {vps_count} VPS assigned. Migrate or delete them first, or use \'force\' to delete all VPS and the node.'))
                                        return
                                    else:
                                        warning_msg = f"Are you sure you want to delete node **{node['name']}** (ID: {node_id})?\n\n"
                                        warning_msg += f"**Location:** {node['location']}\n"
                                        warning_msg += f"**Tags:** {', '.join(node['tags'])}\n\n"
                                        if force and vps_count > 0:
                                                warning_msg += f'**WARNING: Force mode will delete all {vps_count} VPS on this node first!**\n\n'
                                        warning_msg += 'This action cannot be undone!'
                                        embed = create_warning_embed('⚠️ Delete Node', warning_msg)
                                        class ConfirmDelete(discord.ui.View):
                                            def __init__(self, node_id, node_name, force, vps_count):
                                                super().__init__(timeout=60)
                                                self.node_id = node_id
                                                self.node_name = node_name
                                                self.force = force
                                                self.vps_count = vps_count
                                            @discord.ui.button(label='Delete Node', style=discord.ButtonStyle.danger)
                                            async def confirm(self, inter: discord.Interaction, item: discord.ui.Button):
                                                if str(inter.user.id)!= str(ctx.author.id):
                                                    await inter.response.send_message(embed=create_error_embed('Access Denied', 'Only the command author can confirm.'), ephemeral=True)
                                                    return
                                                else:
                                                    await inter.response.defer()
                                                    conn = get_db()
                                                    cur = conn.cursor()
                                                    if self.force and self.vps_count > 0:
                                                            cur.execute('DELETE FROM vps WHERE node_id = ?', (self.node_id,))
                                                    cur.execute('DELETE FROM nodes WHERE id = ?', (self.node_id,))
                                                    conn.commit()
                                                    conn.close()
                                                    msg = f'Node **{self.node_name}** (ID: {self.node_id}) has been deleted.'
                                                    if self.force and self.vps_count > 0:
                                                            msg += f' All {self.vps_count} VPS on the node were also deleted.'
                                                    success_embed = create_success_embed('Node Deleted', msg)
                                                    await inter.followup.send(embed=success_embed)
                                                    self.stop()
                                            @discord.ui.button(label='Cancel', style=discord.ButtonStyle.secondary)
                                            async def cancel(self, inter: discord.Interaction, item: discord.ui.Button):
                                                if str(inter.user.id)!= str(ctx.author.id):
                                                    await inter.response.send_message(embed=create_error_embed('Access Denied', 'Only the command author can cancel.'), ephemeral=True)
                                                else:
                                                    await inter.response.edit_message(embed=create_info_embed('Deletion Cancelled', 'Node deletion was cancelled.'), view=None)
                                                    self.stop()
                                        await ctx.send(embed=embed, view=ConfirmDelete(node_id, node['name'], force, vps_count))
                    else:
                        if sub == 'status':
                            if not args:
                                await ctx.send(embed=create_error_embed('Usage', f'{PREFIX}node status <id>'))
                                return
                            else:
                                try:
                                    node_id = int(args[0])
                                except ValueError:
                                    await ctx.send(embed=create_error_embed('Invalid ID', 'Node ID must be an integer.'))
                                    return
                                node = get_node(node_id)
                                if not node:
                                    await ctx.send(embed=create_error_embed('Not Found', 'Node not found.'))
                                    return
                                else:
                                    embed = create_info_embed(f"Node Status - {node['name']}")
                                    if node['is_local']:
                                        status = '🟢 Local Node'
                                        cpu_usage = get_host_cpu_usage()
                                        ram_usage = get_host_ram_usage()
                                        add_field(embed, 'Status', status, True)
                                        add_field(embed, 'CPU Usage', f'{cpu_usage:.1f}%', True)
                                        add_field(embed, 'RAM Usage', f'{ram_usage:.1f}%', True)
                                    else:
                                        try:
                                            response = requests.get(f"{node['url']}/api/ping", params={'api_key': node['api_key']}, timeout=5)
                                            if response.status_code == 200:
                                                status = '🟢 Online'
                                                try:
                                                    stats_response = requests.get(f"{node['url']}/api/get_host_stats", params={'api_key': node['api_key']}, timeout=5)
                                                    if stats_response.status_code == 200:
                                                        stats = stats_response.json()
                                                        cpu_usage = stats.get('cpu', 0.0)
                                                        ram_usage = stats.get('ram', 0.0)
                                                        add_field(embed, 'CPU Usage', f'{cpu_usage:.1f}%', True)
                                                        add_field(embed, 'RAM Usage', f'{ram_usage:.1f}%', True)
                                                except:
                                                    cpu_usage = 'Unknown'
                                                    ram_usage = 'Unknown'
                                                else:
                                                    pass
                                            else:
                                                status = '🔴 Offline'
                                        except:
                                            status = '🔴 Offline'
                                        add_field(embed, 'Status', status, True)
                                    vps_count = get_current_vps_count(node_id)
                                    capacity = node['total_vps']
                                    usage_percentage = vps_count / capacity * 100 if capacity > 0 else 0
                                    add_field(embed, 'VPS Capacity', f'{vps_count}/{capacity} ({usage_percentage:.1f}%)', True)
                                    add_field(embed, 'Location', node['location'], True)
                                    add_field(embed, 'Tags', ', '.join(node['tags']), True)
                                    if not node['is_local']:
                                        add_field(embed, 'URL', node['url'], False)
                                    await ctx.send(embed=embed)
                        else:
                            embed = create_info_embed('Node Management', f'Manage multi-node infrastructure for {BOT_NAME}')
    class HelpView(discord.ui.View):
        def __init__(self, ctx):
            super().__init__(timeout=300)
            self.ctx = ctx
            self.current_category = 'user'
            myvps = {'👤 User Commands': [{'name': '👤 User Commands', 'commands': [(f'{PREFIX}ping', 'Check bot latency'), (f'{PREFIX}uptime', 'Show host uptime'), (f'{PREFIX}myvps', 'List your VPS'), (f'{PREFIX}manage [@user]', 'Manage your VPS or another user\'s VPS (Admin only)'), (f'{PREFIX}share-user @user <vps_number>', 'Share VPS access'), (f'{PREFIX}share-ruser @user <vps_number>', 'Revoke VPS access'), (f'{PREFIX}Revoke VPS access', 'manage-shared @owner <vps_number>'), (f'{PREFIX}Revoke VPS access', 'Manage shared VPS'), (f'{PREFIX}Revoke VPS access', 'Manage shared VPS'), (f'{PREFIX}Revoke VPS access', 'Manage shared VPS'), (f'{PREFIX}Revoke VPS access', 'Manage shared VPS'), (f'{PREFIX}Revoke VPS access', 'Manage shared VPS'), (f'{PREFIX}Revoke VPS access', 'Manage shared VPS'), (f'{PREFIX}Revoke VPS access', 'Manage shared VPS'), (f'{PREFIX}
            self.update_select()
            self.update_embed()
            self.add_item(self.select)
        def update_select(self):
            """Update the category selection dropdown based on user permissions"""
            self.select = discord.ui.Select(placeholder='Select Category', options=[])
            user_id = str(self.ctx.author.id)
            is_admin_user = user_id == str(MAIN_ADMIN_ID) or user_id in admin_data.get('admins', [])
            is_main_admin_user = user_id == str(MAIN_ADMIN_ID)
            options = []
            basic_categories = ['user', 'coins', 'plans', 'coupons', 'vps', 'ports', 'system', 'bot']
            for category in basic_categories:
                options.append(discord.SelectOption(label=self.command_categories[category]['name'], value=category, emoji=self.get_category_emoji(category)))
            if is_admin_user:
                options.append(discord.SelectOption(label=self.command_categories['nodes']['name'], value='nodes', emoji=self.get_category_emoji('nodes')))
            if is_admin_user:
                options.append(discord.SelectOption(label=self.command_categories['admin']['name'], value='admin', emoji=self.get_category_emoji('admin')))
            if is_main_admin_user:
                options.append(discord.SelectOption(label=self.command_categories['main_admin']['name'], value='main_admin', emoji=self.get_category_emoji('main_admin')))
            self.select.options = options
            self.select.callback = self.select_callback
        async def select_callback(self, interaction: discord.Interaction):
            # irreducible cflow, using cdg fallback
            """Handle category selection"""
            if interaction.user!= self.ctx.author:
                await interaction.response.send_message('This menu is not for you!', ephemeral=True)
                return
                self.current_category = interaction.data['values'][0]
                self.update_embed()
                await interaction.response.edit_message(embed=self.embed, view=self)
                    except discord.errors.NotFound:
                            await interaction.channel.send(embed=self.embed, view=self)
                                    return None
                        except Exception as e:
                                logger.error(f'Error in HelpView select_callback: {e}')
                                    await interaction.response.send_message('An error occurred. Please try again.', ephemeral=True)
        def get_category_emoji(self, category):
            """Get emoji for each category"""
            emojis = {'user': '👤', 'coins': '💰', 'plans': '🚀', 'coupons': '🎟️', 'vps': '🖥️', 'ports': '🔌', 'system': '⚙️', 'bot': '🤖', 'nodes': '🌐', 'admin': '🛡️', 'main_admin': '👑'}
            return emojis.get(category, '📁')
        def update_embed(self):
            """Update the embed based on current category and user permissions"""
            category_data = self.command_categories[self.current_category]
            colors = {'user': 3447003, 'coins': 15844367, 'plans': 15277667, 'coupons': 10181046, 'vps': 3066993, 'ports': 15158332, 'system': 15965202, 'bot': 10181046, 'nodes': 1752220, 'admin': 15105570, 'main_admin': 15844367}
            color = colors.get(self.current_category, 1710618)
            title = f"📚 {BOT_NAME} Command Help - {category_data['name']}"
            description = f"**{category_data['name']}**\nUse the dropdown below to switch categories."
            tips = {'user': 'Tip: Use `!myvps` to see all your VPS and `!manage` to control them.', 'coins': 'Tip: Claim `!daily` every day to build your streak and earn bonus coins!', 'plans': 'Tip: Start with a cheaper plan and upgrade later as you need more resources!', 'coupons': 'Tip: Redeem coupon codes with `!redeem <code>` to get free coins!', 'vps': 'Tip: Snapshots are useful before making major changes to your VPS.', 'ports': 'Tip: Port forwards work for both TCP and UDP protocols.', 'system': 'Tip: Set thresholds to monitor resource usage across nodes.', 'nodes': 'Tip: Use `!node list` to see all available nodes and their status.', 'admin': 'Tip: Always check `!userinfo @user` before modifying VPS.', 'main_admin': 'Tip: Be careful when adding/removing admin privileges.'}
            if self.current_category in tips:
                description += f'\n\n💡 {tips[self.current_category]}'
            self.embed = create_embed(title, description, color)
            commands_text = '\n'.join([f'**{cmd}** - {desc}' for cmd, desc in category_data['commands']])
            add_field(self.embed, 'Commands', commands_text, False)
            footers = {'user': f'{BOT_NAME} VPS Manager • User Commands • Need help? Contact admin', 'coins': f'{BOT_NAME} VPS Manager • Coins & Economy • Earn, Spend, Compete!', 'plans': f'{BOT_NAME} VPS Manager • Plans & Deployment • Flexible VPS Options', 'coupons': f'{BOT_NAME} VPS Manager • Coupon System • Redeem Codes for Coins', 'vps': f'{BOT_NAME} VPS Manager • VPS Management • Snapshots • Cloning', 'ports': f'{BOT_NAME} VPS Manager • Port Forwarding • TCP/UDP Support', 'system': f'{BOT_NAME} VPS Manager • System Monitoring • Resource Management', 'nodes': f'{BOT_NAME} VPS Manager • Multi-Node Management • Distributed Infrastructure', 'bot': f'{BOT_NAME} VPS Manager • Bot Control • Status Management', 'admin': f'{BOT_NAME} VPS Manager • Admin Panel • Restricted Access', 'main_admin': f'{BOT_NAME} VPS Manager • Main Admin • Full System Control'}
            self.embed.set_footer(text=footers.get(self.current_category, f'{BOT_NAME} VPS Manager'))
    @bot.command(name='help')
    async def show_help(ctx):
        """Display the interactive help menu"""
        view = HelpView(ctx)
        await ctx.send(embed=view.embed, view=view)
    @bot.command(name='mangage')
    async def manage_typo(ctx):
        await ctx.send(embed=create_info_embed('Command Correction', f'Did you mean `{PREFIX}manage`? Use the correct command.'))
    @bot.command(name='commands')
    async def commands_alias(ctx):
        """Alias for help command"""
        await show_help(ctx)
    @bot.command(name='stats')
    async def stats_alias(ctx):
        if str(ctx.author.id) == str(MAIN_ADMIN_ID) or str(ctx.author.id) in admin_data.get('admins', []):
            await server_stats(ctx)
        else:
            await ctx.send(embed=create_error_embed('Access Denied', 'This command requires admin privileges.'))
    @bot.command(name='info')
    async def info_alias(ctx, user: discord.Member=None):
        if str(ctx.author.id) == str(MAIN_ADMIN_ID) or str(ctx.author.id) in admin_data.get('admins', []):
            if user:
                await user_info(ctx, user)
            else:
                await ctx.send(embed=create_error_embed('Usage', f'Please specify a user: `{PREFIX}info @user`'))
        else:
            await ctx.send(embed=create_error_embed('Access Denied', 'This command requires admin privileges.'))
    if __name__ == '__main__':
        if DISCORD_TOKEN:
            bot.run(DISCORD_TOKEN)
        else:
            logger.error('No Discord token found in DISCORD_TOKEN environment variable.')
