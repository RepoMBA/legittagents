#!/usr/bin/env python3
"""
Auto Content Publisher

Automated script that runs the entire content workflow:
1. Generate keywords (using provided seeds or defaults)
2. Create content for the top keyword
3. Publish to Medium
4. Post to Twitter
5. Post to LinkedIn

Usage:
    python auto_content_publisher.py [--seeds WORD1 WORD2 ...] [--schedule HH:MM] [--debug]

Example:
    python auto_content_publisher.py --seeds blockchain smart_contracts --schedule 10:00
"""

import os
import sys
import time
import json
import logging
import argparse
import schedule
import re
from datetime import datetime
from typing import List, Optional, Dict, Any, Tuple, Set

# Import the core functions directly from agent_tools
from agent_tools import (
    _generate_keywords_dynamic as generate_keywords_func,
    _create_content_dynamic as create_content_func,
    _publish_medium_dynamic as publish_medium_func,
    _post_linkedin_wrapper as post_linkedin_func,
    _post_twitter_wrapper as post_twitter_func,
    refresh_twitter_token,
    refresh_linkedin_token
)
from core import global_cfg
from core.credentials import users, user
from core.medium import get_unpublished_filenames
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("auto_publisher.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("auto_publisher")

# Load environment variables and configuration
load_dotenv()
global_config = global_cfg()
KEYWORDS_JSON_PATH = global_config["keywords_file"]

# Global variable to track the current keyword being processed
CURRENT_KEYWORD = None
DEBUG_MODE = False
SKIP_STEPS: Set[str] = set()

# Define workflow steps
STEP_GENERATE_KEYWORDS = "generate_keywords"
STEP_CREATE_CONTENT = "create_content"
STEP_PUBLISH_MEDIUM = "publish_medium"
STEP_POST_TWITTER = "post_twitter"
STEP_POST_LINKEDIN = "post_linkedin"

ALL_STEPS = {
    STEP_GENERATE_KEYWORDS,
    STEP_CREATE_CONTENT,
    STEP_PUBLISH_MEDIUM,
    STEP_POST_TWITTER,
    STEP_POST_LINKEDIN
}

def set_debug_mode(enabled=True):
    """Enable or disable debug mode."""
    global DEBUG_MODE
    DEBUG_MODE = enabled
    if enabled:
        logger.setLevel(logging.DEBUG)
        logger.debug("Debug mode enabled")
    else:
        logger.setLevel(logging.INFO)

def set_skip_steps(steps_to_skip: List[str]):
    """Set steps to skip during workflow execution."""
    global SKIP_STEPS
    SKIP_STEPS = set(steps_to_skip)
    if DEBUG_MODE:
        logger.debug(f"Steps to skip: {', '.join(SKIP_STEPS) if SKIP_STEPS else 'None'}")

def should_skip_step(step_name: str) -> bool:
    """Check if a step should be skipped."""
    return step_name in SKIP_STEPS

def set_current_keyword(keyword: Optional[str]):
    """Set the current keyword being processed."""
    global CURRENT_KEYWORD
    CURRENT_KEYWORD = keyword
    if DEBUG_MODE and keyword:
        logger.debug(f"Set current keyword to: {keyword}")

def get_current_keyword() -> Optional[str]:
    """Get the current keyword being processed."""
    return CURRENT_KEYWORD

def load_keywords() -> List[Dict[str, Any]]:
    """Load keywords from the keywords.json file."""
    try:
        if os.path.exists(KEYWORDS_JSON_PATH):
            with open(KEYWORDS_JSON_PATH, "r") as f:
                keywords = json.load(f)
                if DEBUG_MODE:
                    logger.debug(f"Loaded {len(keywords)} keywords from {KEYWORDS_JSON_PATH}")
                return keywords
        if DEBUG_MODE:
            logger.debug(f"Keywords file not found at {KEYWORDS_JSON_PATH}")
        return []
    except Exception as e:
        logger.error(f"Failed to load keywords: {e}")
        return []

def get_top_unused_keyword() -> Optional[str]:
    """Get the topmost keyword that hasn't been used yet."""
    keywords = load_keywords()
    unused_keywords = [k for k in keywords if not k.get("used", False)]
    
    if not unused_keywords:
        logger.info("No unused keywords found")
        return None
    
    # Sort by avg_interest in descending order
    unused_keywords.sort(key=lambda x: x.get("avg_interest", 0), reverse=True)
    top_keyword = unused_keywords[0]["keyword"]
    
    logger.info(f"Selected top keyword: {top_keyword} with interest score: {unused_keywords[0].get('avg_interest', 0)}")
    return top_keyword

def is_auth_error(error_message: str) -> bool:
    """Check if an error message indicates an authentication issue."""
    auth_error_patterns = [
        r"401", 
        r"unauthorized",
        r"auth.*fail",
        r"invalid.*token",
        r"expired.*token",
        r"token.*expired",
        r"authentication.*fail",
        r"not.*authenticated",
        r"auth.*error",
        r"login.*required",
        r"credentials.*invalid"
    ]
    
    error_lower = error_message.lower()
    for pattern in auth_error_patterns:
        if re.search(pattern, error_lower):
            return True
    
    return False

def list_available_users():
    """List all available users from the credentials file."""
    available_users = list(users().keys())
    
    if not available_users:
        print("No users found in credentials file.")
        return
    
    print("\nAvailable users:")
    print("----------------")
    for i, user_id in enumerate(available_users, 1):
        user_data = user(user_id)
        platforms = []
        if 'twitter' in user_data:
            platforms.append("Twitter")
        if 'linkedin' in user_data:
            platforms.append("LinkedIn")
        if 'medium' in user_data:
            platforms.append("Medium")
        
        platforms_str = ", ".join(platforms) if platforms else "No platforms configured"
        print(f"{i}. {user_id} ({platforms_str})")
    print()

def set_active_user(user_id: str):
    """Set the active user for the current session."""
    # This is just for logging purposes - the actual user selection
    # happens when calling functions that use the credentials
    logger.info(f"Using credentials for user: {user_id}")
    
    # Check if the user exists
    try:
        user_data = user(user_id)
        platforms = []
        if 'twitter' in user_data:
            platforms.append("Twitter")
        if 'linkedin' in user_data:
            platforms.append("LinkedIn")
        if 'medium' in user_data:
            platforms.append("Medium")
        
        platforms_str = ", ".join(platforms) if platforms else "No platforms configured"
        logger.info(f"User {user_id} has access to: {platforms_str}")
        
        # Set environment variable for other components that might use it
        os.environ["ACTIVE_USER"] = user_id
        return True
    except KeyError:
        logger.error(f"User '{user_id}' not found in credentials file.")
        return False

def post_to_twitter_with_retry(user_id: Optional[str] = None) -> Tuple[bool, Dict]:
    """Post to Twitter with automatic token refresh on auth failure."""
    logger.info("Posting to Twitter...")
    
    # If user_id is provided, we need to set it in the environment
    # so the underlying functions use the right credentials
    if user_id:
        os.environ["ACTIVE_USER"] = user_id
    
    try:
        result = post_twitter_func()
        logger.info("Posted to Twitter successfully")
        return True, result
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error posting to Twitter: {error_msg}")
        
        # Check if this is an authentication error
        if is_auth_error(error_msg):
            logger.info("Detected Twitter authentication issue. Refreshing token...")
            try:
                refresh_twitter_token()
                logger.info("Twitter token refreshed successfully. Retrying post...")
                # Wait a moment for the token to be properly saved
                time.sleep(3)
                
                # Retry the post
                try:
                    result = post_twitter_func()
                    logger.info("Posted to Twitter successfully after token refresh")
                    return True, result
                except Exception as retry_e:
                    logger.error(f"Failed to post to Twitter even after token refresh: {retry_e}")
                    return False, {"status": "error", "message": str(retry_e)}
                    
            except Exception as refresh_e:
                logger.error(f"Failed to refresh Twitter token: {refresh_e}")
                return False, {"status": "error", "message": f"Twitter token refresh failed: {refresh_e}"}
        
        return False, {"status": "error", "message": error_msg}

def post_to_linkedin_with_retry(user_id: Optional[str] = None) -> Tuple[bool, Dict]:
    """Post to LinkedIn with automatic token refresh on auth failure."""
    logger.info("Posting to LinkedIn...")
    
    # If user_id is provided, we need to set it in the environment
    # so the underlying functions use the right credentials
    if user_id:
        os.environ["ACTIVE_USER"] = user_id
    
    try:
        result = post_linkedin_func()
        logger.info("Posted to LinkedIn successfully")
        return True, result
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error posting to LinkedIn: {error_msg}")
        
        # Check if this is an authentication error
        if is_auth_error(error_msg):
            logger.info("Detected LinkedIn authentication issue. Refreshing token...")
            try:
                refresh_linkedin_token()
                logger.info("LinkedIn token refreshed successfully. Retrying post...")
                # Wait a moment for the token to be properly saved
                time.sleep(3)
                
                # Retry the post
                try:
                    result = post_linkedin_func()
                    logger.info("Posted to LinkedIn successfully after token refresh")
                    return True, result
                except Exception as retry_e:
                    logger.error(f"Failed to post to LinkedIn even after token refresh: {retry_e}")
                    return False, {"status": "error", "message": str(retry_e)}
                    
            except Exception as refresh_e:
                logger.error(f"Failed to refresh LinkedIn token: {refresh_e}")
                return False, {"status": "error", "message": f"LinkedIn token refresh failed: {refresh_e}"}
        
        return False, {"status": "error", "message": error_msg}

def run_workflow(seeds: Optional[List[str]] = None, user_id: Optional[str] = None) -> bool:
    """
    Run the full content workflow from keywords to social posting.
    Returns True if successful, False if any step fails.
    
    Args:
        seeds: Optional list of seed words for keyword generation
        user_id: Optional user ID to use for credentials
    """
    try:
        logger.info("=" * 60)
        logger.info("STARTING AUTOMATED CONTENT WORKFLOW")
        logger.info("=" * 60)
        
        # Set active user if provided
        if user_id:
            if not set_active_user(user_id):
                return False
        
        # STEP 1: Generate keywords if needed
        if should_skip_step(STEP_GENERATE_KEYWORDS):
            logger.info(f"SKIPPING: {STEP_GENERATE_KEYWORDS}")
        elif not os.path.exists(KEYWORDS_JSON_PATH) or not get_top_unused_keyword():
            logger.info("No unused keywords found, generating new ones...")
            
            # Convert seeds list to comma-separated string if provided
            seeds_str = ""
            if seeds and len(seeds) > 0:
                seeds_str = ", ".join(seeds)
                logger.info(f"Using provided seed words: {seeds_str}")
            else:
                logger.info("Using default seed words")
            
            # Generate keywords
            result = generate_keywords_func(seeds_str)
            
            if "error" in result or not os.path.exists(KEYWORDS_JSON_PATH):
                logger.error("Failed to generate keywords")
                return False
                
            logger.info("Keywords generated successfully")
        else:
            logger.info("Using existing keywords from keywords.json")
        
        # STEP 2: Get the top unused keyword
        keyword = get_top_unused_keyword()
        if not keyword:
            logger.error("Failed to get an unused keyword")
            return False
        
        # Set as current keyword for tracking
        set_current_keyword(keyword)
        logger.info(f"Selected keyword for processing: {keyword}")
        
        # STEP 3: Create content for the selected keyword
        if should_skip_step(STEP_CREATE_CONTENT):
            logger.info(f"SKIPPING: {STEP_CREATE_CONTENT}")
        else:
            logger.info(f"Creating content for keyword: {keyword}")
            content_result = create_content_func(keyword)
            
            if "error" in content_result or content_result.get("status") == "error":
                logger.error(f"Content creation failed: {content_result}")
                return False
                
            logger.info("Content created successfully")
        
        # STEP 4: Publish to Medium
        if should_skip_step(STEP_PUBLISH_MEDIUM):
            logger.info(f"SKIPPING: {STEP_PUBLISH_MEDIUM}")
        else:
            logger.info("Publishing to Medium...")
            
            # Get unpublished files to check if there's anything to publish
            unpublished = get_unpublished_filenames()
            if not unpublished:
                logger.error("No unpublished content found for Medium")
                return False
            
            # Find the file matching our keyword
            filename = ""
            for file in unpublished:
                if keyword.lower().replace(" ", "_") in file.lower() or keyword.lower().replace(" ", "-") in file.lower():
                    filename = file
                    logger.info(f"Found matching file for keyword '{keyword}': {filename}")
                    break
            
            if not filename:
                logger.warning(f"No file found matching keyword '{keyword}'. Using first available file.")
                filename = unpublished[0]
            
            # Publish to Medium
            medium_result = publish_medium_func(filename)
            
            if "error" in medium_result or medium_result.get("status") == "error":
                logger.error(f"Medium publishing failed: {medium_result}")
                return False
                
            logger.info("Published to Medium successfully")
        
        # STEP 5: Post to Twitter with auto-refresh
        if should_skip_step(STEP_POST_TWITTER):
            logger.info(f"SKIPPING: {STEP_POST_TWITTER}")
        else:
            success, twitter_result = post_to_twitter_with_retry(user_id)
            if not success:
                logger.error(f"Twitter posting failed even after token refresh attempt: {twitter_result}")
                return False
        
        # STEP 6: Post to LinkedIn with auto-refresh
        if should_skip_step(STEP_POST_LINKEDIN):
            logger.info(f"SKIPPING: {STEP_POST_LINKEDIN}")
        else:
            success, linkedin_result = post_to_linkedin_with_retry(user_id)
            if not success:
                logger.error(f"LinkedIn posting failed even after token refresh attempt: {linkedin_result}")
                return False
        
        # Workflow completed successfully
        logger.info("=" * 60)
        logger.info("WORKFLOW COMPLETED SUCCESSFULLY")
        logger.info("=" * 60)
        return True
        
    except Exception as e:
        logger.error(f"Error in workflow: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

def scheduled_run(seeds: Optional[List[str]] = None, user_id: Optional[str] = None):
    """Function to be called by the scheduler."""
    logger.info(f"Running scheduled workflow at {datetime.now().strftime('%H:%M:%S')}")
    run_workflow(seeds, user_id)

def main():
    parser = argparse.ArgumentParser(description="Automated Content Creation and Publishing")
    parser.add_argument("--seeds", nargs="+", help="Seed words for keyword generation (space separated)")
    parser.add_argument("--schedule", help="Schedule time in HH:MM format (24-hour)")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode with verbose logging")
    parser.add_argument("--skip", nargs="+", choices=list(ALL_STEPS), 
                        help="Skip specific steps (use with --debug). Available steps: " + ", ".join(ALL_STEPS))
    parser.add_argument("--user", help="User ID to use for credentials")
    parser.add_argument("--list-users", action="store_true", help="List all available users from credentials file")
    
    args = parser.parse_args()
    
    # Handle --list-users flag first
    if args.list_users:
        list_available_users()
        sys.exit(0)
    
    if args.debug:
        set_debug_mode(True)
        
    if args.skip:
        if not args.debug:
            logger.warning("--skip flag requires --debug flag. Enabling debug mode automatically.")
            set_debug_mode(True)
        set_skip_steps(args.skip)
    
    # Validate user if provided
    if args.user:
        try:
            user(args.user)  # This will raise KeyError if user doesn't exist
        except KeyError:
            print(f"Error: User '{args.user}' not found in credentials file.")
            print("Use --list-users to see available users.")
            sys.exit(1)
    
    seed_words = None
    if args.seeds:
        seed_words = []
        for seed in args.seeds:
            # Handle both comma and space separated inputs
            if "," in seed:
                seed_words.extend([s.strip() for s in seed.split(",") if s.strip()])
            else:
                seed_words.append(seed.strip())
    
    if args.schedule:
        try:
            # Validate time format
            hour, minute = map(int, args.schedule.split(":"))
            if not (0 <= hour < 24 and 0 <= minute < 60):
                raise ValueError("Invalid time")
                
            logger.info(f"Scheduling workflow to run daily at {args.schedule}")
            schedule.every().day.at(args.schedule).do(scheduled_run, seeds=seed_words, user_id=args.user)
            
            logger.info("Scheduler started. Press Ctrl+C to exit.")
            while True:
                schedule.run_pending()
                time.sleep(60)  # Check every minute
        except (ValueError, IndexError):
            logger.error("Invalid schedule time format. Use HH:MM (24-hour format)")
            sys.exit(1)
    else:
        # Run immediately
        success = run_workflow(seed_words, args.user)
        sys.exit(0 if success else 1)

if __name__ == "__main__":
    main() 