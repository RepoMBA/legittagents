#!/usr/bin/env python3
"""
Social Media Publisher

This script handles the social media publishing workflow:
1. Post to Twitter 
2. Post to LinkedIn

Usage:
    python social_publisher.py [--platform PLATFORM] [--user USER_ID] [--schedule HH:MM] [--debug]

Example:
    python social_publisher.py --platform twitter --user shresth
"""

import os
import sys
import time
import logging
import argparse
import schedule
import re
from datetime import datetime
from typing import List, Optional, Dict, Any, Set, Tuple

# Import the core functions
from agent_tools import (
    _post_linkedin_wrapper as post_linkedin_func,
    _post_twitter_wrapper as post_twitter_func,
    refresh_linkedin_token
)
from core.twitter_token import refresh_token_auto as refresh_twitter_token_auto
from core import global_cfg
from core.credentials import users, user
from Utils.google_drive import get_unpublished_filenames, update_social_post
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("social_publisher.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("social_publisher")

# Load environment variables and configuration
load_dotenv()
global_config = global_cfg()

# Global variables
DEBUG_MODE = False
SKIP_STEPS: Set[str] = set()
RUN_ONLY_STEPS: Set[str] = set()

# Define workflow steps
STEP_POST_TWITTER = "post_twitter"
STEP_POST_LINKEDIN = "post_linkedin"

ALL_STEPS = {
    STEP_POST_TWITTER,
    STEP_POST_LINKEDIN
}

PLATFORMS = ["twitter", "linkedin", "all"]

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

def set_run_only_steps(steps_to_run: List[str]):
    """Set steps to run during workflow execution (all others will be skipped)."""
    global RUN_ONLY_STEPS
    RUN_ONLY_STEPS = set(steps_to_run)
    logger.info(f"Only running steps: {', '.join(RUN_ONLY_STEPS)}")

def should_skip_step(step_name: str) -> bool:
    """Check if a step should be skipped."""
    # If specific steps are set to run, skip everything else
    if RUN_ONLY_STEPS:
        return step_name not in RUN_ONLY_STEPS
    # Otherwise use the skip list
    return step_name in SKIP_STEPS

def is_auth_error(error_message: str) -> bool:
    """Check if an error message indicates an authentication issue."""
    # Direct check for Twitter API 401 Unauthorized error
    if "401 Client Error: Unauthorized for url" in error_message:
        return True
        
    # General auth error patterns as fallback
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
        
        platforms_str = ", ".join(platforms) if platforms else "No platforms configured"
        logger.info(f"User {user_id} has access to: {platforms_str}")
        
        # Set environment variable for other components that might use it
        os.environ["ACTIVE_USER"] = user_id
        return True
    except KeyError:
        logger.error(f"User '{user_id}' not found in credentials file.")
        return False

def post_to_twitter_with_retry(user_id: Optional[str] = None, article_id: Optional[str] = None, filename: Optional[str] = None) -> Tuple[bool, Dict]:
    """Post a single tweet to Twitter with automatic token refresh on auth failure."""
    logger.info(f"Posting to Twitter: {filename}")
    
    # If user_id is provided, set it in the environment
    if user_id:
        os.environ["ACTIVE_USER"] = user_id
    
    # First attempt to post
    try:
        result = post_twitter_func()
        published = result.get("published", []) if isinstance(result, dict) else []
        failed = result.get("failed", []) if isinstance(result, dict) else []
        
        # Check if successful
        if published:
            if not failed:
                logger.info(f"Posted {len(published)} tweet(s) successfully")
            else:
                logger.warning(f"Partial success: {len(published)} tweet(s) posted, {len(failed)} failed")
                for item in failed:
                    logger.error(f"Tweet failed for file {item.get('filename', '?')}: {item.get('error')}")
            return True, result
        
        # No tweets published - log error details
        error_details = ""
        if isinstance(result, dict):
            if result.get("failed") and len(result["failed"]) > 0:
                error_details = " - Errors: " + ", ".join([f"{item.get('filename', '?')}: {item.get('error', 'Unknown error')}" for item in result["failed"]])
            elif result.get("error"):
                error_details = f" - Error: {result['error']}"
            elif result.get("message"):
                error_details = f" - Message: {result['message']}"
        
        logger.error(f"No tweets published{error_details}")
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error posting to Twitter: {error_msg}")
        result = {"status": "error", "message": error_msg}
    
    # If we got here, the first attempt failed - check if it's an auth error
    print("ERROR MSG:", error_details, is_auth_error(error_details))

    if is_auth_error(error_details):
        print("is_auth_error")
        logger.info("Detected authentication issue. Refreshing Twitter token...")
        try:
            refresh_twitter_token_auto()
            logger.info("Twitter token refreshed. Retrying post...")
            
            # Second attempt after token refresh
            retry_result = post_twitter_func()
            published = retry_result.get("published", []) if isinstance(retry_result, dict) else []
            failed = retry_result.get("failed", []) if isinstance(retry_result, dict) else []
            
            if published:
                if not failed:
                    logger.info(f"Posted {len(published)} tweet(s) successfully after token refresh")
                else:
                    logger.warning(f"Partial success after token refresh: {len(published)} tweet(s) posted, {len(failed)} failed")
                    for item in failed:
                        logger.error(f"Tweet failed for file {item.get('filename', '?')}: {item.get('error')}")
                return True, retry_result
            
            # No tweets published on retry - log error
            error_details = ""
            if isinstance(retry_result, dict):
                if retry_result.get("failed"):
                    error_details = " - Errors: " + ", ".join([f"{item.get('filename', '?')}: {item.get('error', 'Unknown error')}" for item in retry_result["failed"]])
                elif retry_result.get("error"):
                    error_details = f" - Error: {retry_result['error']}"
                elif retry_result.get("message"):
                    error_details = f" - Message: {retry_result['message']}"
            
            logger.error(f"No tweets published after token refresh{error_details}")
            return False, retry_result
            
        except Exception as refresh_e:
            logger.error(f"Failed to refresh Twitter token: {refresh_e}")
            return False, {"status": "error", "message": f"Token refresh failed: {str(refresh_e)}"}
    
    # Return the result of the first attempt
    return False, result

def post_to_linkedin_with_retry(user_id: Optional[str] = None) -> Tuple[bool, Dict]:
    """Post to LinkedIn with automatic token refresh on auth failure."""
    logger.info("Posting to LinkedIn...")
    
    # If user_id is provided, we need to set it in the environment
    # so the underlying functions use the right credentials
    if user_id:
        os.environ["ACTIVE_USER"] = user_id
    
    try:
        result = post_linkedin_func()
        published = result.get("published", []) if isinstance(result, dict) else []
        failed    = result.get("failed", [])    if isinstance(result, dict) else []

        if not published:
            error_details = ""
            if isinstance(result, dict):
                if result.get("failed") and len(result["failed"]) > 0:
                    error_details = " - Errors: " + ", ".join([f"{item.get('filename', '?')}: {item.get('error', 'Unknown error')}" for item in result["failed"]])
                elif result.get("error"):
                    error_details = f" - Error: {result['error']}"
                elif result.get("message"):
                    error_details = f" - Message: {result['message']}"
            
            logger.error(f"post_linkedin returned no published posts – treating as failure{error_details}")
            raise Exception("no_posts_published")
        if failed:
            logger.warning(f"Partial success: {len(published)} LinkedIn post(s) published, {len(failed)} failed")
            # Log detailed errors
            for item in failed:
                logger.error(f"LinkedIn post failed for file {item.get('filename', '?')}: {item.get('error')}")
        else:
            logger.info(f"Posted {len(published)} LinkedIn post(s) successfully")
        # Dump captured stdout logs at DEBUG level for troubleshooting
        if result.get("logs"):
            logger.debug("Detailed LinkedIn publish logs:\n" + result["logs"])
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
                    published = result.get("published", []) if isinstance(result, dict) else []
                    failed    = result.get("failed", [])    if isinstance(result, dict) else []

                    if not published:
                        logger.error("post_linkedin returned no published posts after refresh – failure")
                        raise Exception("no_posts_published")
                    if failed:
                        logger.warning(f"Partial success after refresh: {len(published)} LinkedIn post(s) published, {len(failed)} failed")
                    else:
                        logger.info(f"Posted {len(published)} LinkedIn post(s) successfully after token refresh")
                    return True, result
                except Exception as retry_e:
                    logger.error(f"Failed to post to LinkedIn even after token refresh: {retry_e}")
                    return False, {"status": "error", "message": str(retry_e)}
                    
            except Exception as refresh_e:
                logger.error(f"Failed to refresh LinkedIn token: {refresh_e}")
                return False, {"status": "error", "message": f"LinkedIn token refresh failed: {refresh_e}"}
        
        return False, {"status": "error", "message": error_msg}

def run_workflow(platform: str = "all", user_id: Optional[str] = None) -> bool:
    """
    Run the social media publishing workflow.
    
    Args:
        platform: Platform to post to ("twitter", "linkedin", or "all")
        user_id: Optional user ID to use for credentials
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        logger.info("=" * 60)
        logger.info("STARTING SOCIAL MEDIA PUBLISHING WORKFLOW")
        logger.info("=" * 60)
        
        # Set active user if provided
        if user_id:
            if not set_active_user(user_id):
                return False
            
        # STEP 1: Post to Twitter
        if (platform == "twitter" or platform == "all") and not should_skip_step(STEP_POST_TWITTER):
            # Get pending Twitter posts for this user
            pending_posts = get_unpublished_filenames("twitter", user_id)
            
            if not pending_posts:
                logger.info("No pending Twitter posts found")
            else:
                logger.info(f"Found {len(pending_posts)} pending Twitter posts")
                
                for post in pending_posts:
                    article_id = post["article_id"]
                    filename = post["filename"]
                    logger.info(f"Posting article {article_id} ({filename}) to Twitter")
                    
                    success, result = post_to_twitter_with_retry(user_id)
                    
                    if success:
                        # Extract the Twitter URL
                        post_url = ""
                        if isinstance(result, dict):
                            if "published" in result and result["published"] and len(result["published"]) > 0:
                                post_url = result["published"][0].get("url", "")
                        
                        # Update the social media post record
                        try:
                            update_social_post(
                                employee_name=user_id or "",  # Ensure non-None value
                                platform="twitter",
                                article_id=article_id,
                                updates={
                                    "posted": True,
                                    "post_url": post_url
                                }
                            )
                            logger.info(f"Updated Twitter post status for article {article_id}")
                        except Exception as e:
                            logger.error(f"Failed to update Twitter post status: {e}")
                    else:
                        error_message = result.get("message", "") if isinstance(result, dict) else ""
                        logger.error(f"Failed to post to Twitter for article {article_id}: {error_message}")
        elif should_skip_step(STEP_POST_TWITTER):
            logger.info(f"SKIPPING: {STEP_POST_TWITTER}")
            
        # STEP 2: Post to LinkedIn
        if (platform == "linkedin" or platform == "all") and not should_skip_step(STEP_POST_LINKEDIN):
            # Get pending LinkedIn posts for this user
            pending_posts = get_unpublished_filenames("linkedin", user_id)
            
            if not pending_posts:
                logger.info("No pending LinkedIn posts found")
            else:
                logger.info(f"Found {len(pending_posts)} pending LinkedIn posts")
                
                for post in pending_posts:
                    article_id = post["article_id"]
                    filename = post["filename"]
                    logger.info(f"Posting article {article_id} ({filename}) to LinkedIn")
                    
                    success, result = post_to_linkedin_with_retry(user_id)
                    
                    if success:
                        # Extract the LinkedIn URL
                        post_url = ""
                        if isinstance(result, dict):
                            if "published" in result and result["published"] and len(result["published"]) > 0:
                                post_url = result["published"][0].get("url", "")
                        
                        # Update the social media post record
                        try:
                            update_social_post(
                                employee_name=user_id or "",  # Ensure non-None value
                                platform="linkedin",
                                article_id=article_id,
                                updates={
                                    "posted": True,
                                    "post_url": post_url
                                }
                            )
                            logger.info(f"Updated LinkedIn post status for article {article_id}")
                        except Exception as e:
                            logger.error(f"Failed to update LinkedIn post status: {e}")
                    else:
                        error_message = result.get("message", "") if isinstance(result, dict) else ""
                        logger.error(f"Failed to post to LinkedIn for article {article_id}: {error_message}")
        elif should_skip_step(STEP_POST_LINKEDIN):
            logger.info(f"SKIPPING: {STEP_POST_LINKEDIN}")
        
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

def scheduled_run(platform: str = "all", user_id: Optional[str] = None):
    """Function to be called by the scheduler."""
    logger.info(f"Running scheduled workflow at {datetime.now().strftime('%H:%M:%S')}")
    run_workflow(platform, user_id)

def main():
    parser = argparse.ArgumentParser(description="Social Media Publishing Tool")
    parser.add_argument("--platform", choices=PLATFORMS, default="all", 
                        help="Platform to post to (twitter, linkedin, or all)")
    parser.add_argument("--schedule", help="Schedule time in HH:MM format (24-hour)")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode with verbose logging")
    
    # Create a mutually exclusive group for run and skip
    run_skip_group = parser.add_mutually_exclusive_group()
    run_skip_group.add_argument("--skip", nargs="+", choices=list(ALL_STEPS), 
                      help="Skip specific steps (use with --debug). Available steps: " + ", ".join(ALL_STEPS))
    run_skip_group.add_argument("--run", nargs="+", choices=list(ALL_STEPS),
                      help="Run only specific steps (inverse of --skip). Available steps: " + ", ".join(ALL_STEPS))
                      
    parser.add_argument("--user", help="User ID to use for credentials (optional). If omitted the script will iterate through every (user, platform) pair with pending posts.")
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
    
    if args.run:
        set_run_only_steps(args.run)
    
    # Helper: run for all pending pairs when --user not supplied
    def _run_all_pending():
        pending_overall = get_unpublished_filenames()
        if not pending_overall:
            logger.info("No pending social posts found – nothing to do.")
            return True

        pairs: Set[Tuple[str, str]] = set()
        for entry in pending_overall:
            pairs.add((entry["employee_name"], entry["platform"]))

        logger.info(f"Will process {len(pairs)} (user, platform) pair(s): {pairs}")

        overall_success = True
        for user_id, platform in pairs:
            ok = run_workflow(platform, user_id)
            overall_success = overall_success and ok
        return overall_success

    if args.user:
        # Validate user
        try:
            user(args.user)
        except KeyError:
            print(f"Error: User '{args.user}' not found in credentials file.")
            print("Use --list-users to see available users.")
            sys.exit(1)
    
    if args.schedule:
        try:
            # Validate time format
            hour, minute = map(int, args.schedule.split(":"))
            if not (0 <= hour < 24 and 0 <= minute < 60):
                raise ValueError("Invalid time")
                
            logger.info(f"Scheduling workflow to run daily at {args.schedule}")
            schedule.every().day.at(args.schedule).do(scheduled_run, platform=args.platform, user_id=args.user)
            
            logger.info("Scheduler started. Press Ctrl+C to exit.")
            while True:
                schedule.run_pending()
                time.sleep(60)  # Check every minute
        except (ValueError, IndexError):
            logger.error("Invalid schedule time format. Use HH:MM (24-hour format)")
            sys.exit(1)
    else:
        # Run immediately – either for a specific user or for all pending pairs
        if args.user:
            success = run_workflow(args.platform, args.user)
        else:
            success = _run_all_pending()
        sys.exit(0 if success else 1)

if __name__ == "__main__":
    main() 