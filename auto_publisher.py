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
DEFAULT_KEYWORDS_PATH = global_config["keywords_file"]
KEYWORDS_JSON_PATH = DEFAULT_KEYWORDS_PATH  # Will be changed if seeds are provided

# Global variable to track the current keyword being processed
CURRENT_KEYWORD = None
DEBUG_MODE = False
SKIP_STEPS: Set[str] = set()
RUN_ONLY_STEPS: Set[str] = set()

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

def set_current_keyword(keyword: Optional[str]):
    """Set the current keyword being processed."""
    global CURRENT_KEYWORD
    CURRENT_KEYWORD = keyword
    if DEBUG_MODE and keyword:
        logger.debug(f"Set current keyword to: {keyword}")

def get_current_keyword() -> Optional[str]:
    """Get the current keyword being processed."""
    return CURRENT_KEYWORD

def load_keywords(file_path=None) -> List[Dict[str, Any]]:
    """Load keywords from the specified keywords file or default."""
    path_to_use = file_path or KEYWORDS_JSON_PATH
    try:
        if os.path.exists(path_to_use):
            with open(path_to_use, "r") as f:
                keywords = json.load(f)
                if DEBUG_MODE:
                    logger.debug(f"Loaded {len(keywords)} keywords from {path_to_use}")
                return keywords
        if DEBUG_MODE:
            logger.debug(f"Keywords file not found at {path_to_use}")
        return []
    except Exception as e:
        logger.error(f"Failed to load keywords: {e}")
        return []

def get_top_unused_keyword(file_path=None) -> Optional[str]:
    """Get the topmost keyword that hasn't been used yet."""
    keywords = load_keywords(file_path)
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
        result = post_twitter_func(user_id)
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
                    result = post_twitter_func(user_id)
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

def run_workflow(seeds: Optional[List[str]] = None, user_id: Optional[str] = None, browser_type: str = "chromium") -> bool:
    """
    Run the complete workflow from keyword generation to social media posting.
    
    Args:
        seeds: Optional list of seed words for keyword generation
        user_id: Optional user ID to use for credentials
        browser_type: Browser to use for Medium publishing ("chromium" or "firefox")
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        logger.info("=" * 60)
        logger.info("STARTING AUTOMATED CONTENT WORKFLOW")
        logger.info("=" * 60)
        
        # Set active user if provided
        if user_id:
            if not set_active_user(user_id):
                return False
        
        # Set up the keywords path - use a temporary file if seeds are provided
        global KEYWORDS_JSON_PATH
        temp_keywords_file = None
        
        if seeds:
            try:
                # Create a temporary keywords file path when seeds are provided
                temp_dir = os.path.dirname(DEFAULT_KEYWORDS_PATH)
                
                # Ensure the directory exists
                os.makedirs(temp_dir, exist_ok=True)
                
                # Create a unique filename in the same directory
                temp_keywords_file = os.path.join(temp_dir, f"temp_keywords_{int(time.time())}.json")
                KEYWORDS_JSON_PATH = temp_keywords_file
                logger.info(f"Using temporary keywords file: {KEYWORDS_JSON_PATH}")
                
                # Test if the directory is writable
                try:
                    with open(KEYWORDS_JSON_PATH, 'w') as f:
                        f.write('[]')  # Initialize with empty array
                    logger.info("Temporary file created successfully")
                except IOError as e:
                    logger.error(f"Cannot write to temporary file location: {e}")
                    logger.info("Falling back to default keywords file")
                    KEYWORDS_JSON_PATH = DEFAULT_KEYWORDS_PATH
                    temp_keywords_file = None
            except Exception as e:
                logger.error(f"Error setting up temporary file: {e}")
                logger.info("Falling back to default keywords file")
                KEYWORDS_JSON_PATH = DEFAULT_KEYWORDS_PATH
                temp_keywords_file = None
        else:
            # Use the default keywords file when no seeds are provided
            KEYWORDS_JSON_PATH = DEFAULT_KEYWORDS_PATH
            logger.info(f"Using default keywords file: {KEYWORDS_JSON_PATH}")
        
        # STEP 1: Generate keywords if needed
        if should_skip_step(STEP_GENERATE_KEYWORDS):
            logger.info(f"SKIPPING: {STEP_GENERATE_KEYWORDS}")
        else:
            if seeds:
                # Always generate new keywords when seeds are provided
                logger.info("Generating keywords from provided seeds...")
                
                # Convert seeds list to comma-separated string
                seeds_str = ", ".join(seeds)
                logger.info(f"Using provided seed words: {seeds_str}")
                
                # Generate keywords with better error handling
                try:
                    # Pass the temporary file path to the generate_keywords function
                    result = generate_keywords_func(seeds_str, output_file=KEYWORDS_JSON_PATH)
                    
                    if isinstance(result, dict) and "error" in result:
                        logger.error(f"Error from keyword generation function: {result['error']}")
                        return False
                    
                    if not os.path.exists(KEYWORDS_JSON_PATH):
                        logger.error(f"Expected keywords file {KEYWORDS_JSON_PATH} was not created")
                        return False
                        
                    # Verify the file has valid content
                    try:
                        with open(KEYWORDS_JSON_PATH, 'r') as f:
                            keywords_data = json.load(f)
                            if not keywords_data:
                                logger.warning("Generated keywords file is empty")
                    except json.JSONDecodeError:
                        logger.error("Generated keywords file is not valid JSON")
                        return False
                    
                    logger.info("Keywords generated successfully")
                except Exception as e:
                    logger.error(f"Exception during keyword generation: {str(e)}")
                    import traceback
                    logger.error(traceback.format_exc())
                    return False
            elif not os.path.exists(DEFAULT_KEYWORDS_PATH) or not get_top_unused_keyword(DEFAULT_KEYWORDS_PATH):
                # Only generate keywords with default seeds if the default file doesn't exist
                # or doesn't have unused keywords
                logger.info("No unused keywords found in default file, generating new ones...")
                logger.info("Using default seed words")
                
                # Generate keywords
                result = generate_keywords_func("")
                
                if "error" in result or not os.path.exists(DEFAULT_KEYWORDS_PATH):
                    logger.error("Failed to generate keywords")
                    return False
                    
                logger.info("Keywords generated successfully")
            else:
                logger.info("Using existing keywords from default keywords.json")
        
        # STEP 2: Get the top unused keyword
        keyword = get_top_unused_keyword(KEYWORDS_JSON_PATH)
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
            medium_result = publish_medium_func(filename=filename, browser_type=browser_type)
            
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
        
        # Cleanup temporary file if created, but first append its keywords to the default file
        try:
            if temp_keywords_file and os.path.exists(temp_keywords_file):
                # Load keywords from temporary file
                temp_keywords = []
                try:
                    with open(temp_keywords_file, 'r') as f:
                        temp_keywords = json.load(f)
                    logger.info(f"Loaded {len(temp_keywords)} keywords from temporary file")
                except Exception as e:
                    logger.error(f"Failed to load keywords from temporary file: {e}")
                
                # Load keywords from default file
                default_keywords = []
                try:
                    if os.path.exists(DEFAULT_KEYWORDS_PATH):
                        with open(DEFAULT_KEYWORDS_PATH, 'r') as f:
                            default_keywords = json.load(f)
                        logger.info(f"Loaded {len(default_keywords)} keywords from default file")
                except Exception as e:
                    logger.error(f"Failed to load keywords from default file: {e}")
                
                # Mark the keyword we used as used=true in temporary keywords
                if keyword:
                    for kw in temp_keywords:
                        if kw["keyword"] == keyword:
                            kw["used"] = True
                            logger.info(f"Marked keyword '{keyword}' as used")
                
                # Create a map of existing keywords in default file to avoid duplicates
                existing_keywords = {kw["keyword"]: kw for kw in default_keywords}
                
                # Add or update keywords from temporary file
                for temp_kw in temp_keywords:
                    kw_name = temp_kw["keyword"]
                    if kw_name in existing_keywords:
                        # Update the existing keyword with the higher interest score
                        if temp_kw.get("avg_interest", 0) > existing_keywords[kw_name].get("avg_interest", 0):
                            existing_keywords[kw_name]["avg_interest"] = temp_kw["avg_interest"]
                            logger.debug(f"Updated interest score for '{kw_name}'")
                        
                        # Preserve the used status
                        if temp_kw.get("used", False):
                            existing_keywords[kw_name]["used"] = True
                    else:
                        # Add the new keyword
                        existing_keywords[kw_name] = temp_kw
                        logger.debug(f"Added new keyword '{kw_name}'")
                
                # Convert back to list and sort by avg_interest (descending)
                combined_keywords = list(existing_keywords.values())
                combined_keywords.sort(key=lambda x: x.get("avg_interest", 0), reverse=True)
                
                # Save the combined list to default file
                try:
                    os.makedirs(os.path.dirname(DEFAULT_KEYWORDS_PATH), exist_ok=True)
                    with open(DEFAULT_KEYWORDS_PATH, 'w') as f:
                        json.dump(combined_keywords, f, indent=2)
                    logger.info(f"Saved {len(combined_keywords)} combined keywords to default file")
                except Exception as e:
                    logger.error(f"Failed to save combined keywords to default file: {e}")
                
                # Delete the temporary file
                os.remove(temp_keywords_file)
                logger.info(f"Removed temporary keywords file: {temp_keywords_file}")
        except Exception as e:
            logger.warning(f"Failed to process or remove temporary keywords file: {e}")
            import traceback
            logger.debug(traceback.format_exc())
        
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

def scheduled_run(seeds: Optional[List[str]] = None, user_id: Optional[str] = None, browser_type: str = "chromium"):
    """Function to be called by the scheduler."""
    logger.info(f"Running scheduled workflow at {datetime.now().strftime('%H:%M:%S')}")
    run_workflow(seeds, user_id, browser_type)

def main():
    parser = argparse.ArgumentParser(description="Auto Content Publisher")
    parser.add_argument("--seeds", help="Comma-separated list of seed words for keyword generation")
    parser.add_argument("--schedule", help="Schedule time in HH:MM format (24-hour)")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode with verbose logging")
    parser.add_argument("--user", help="User ID to use for credentials (optional)")
    parser.add_argument("--browser", choices=["chromium", "firefox"], default="chromium", 
                      help="Browser to use for Medium publishing (chromium or firefox)")
    
    # Create a mutually exclusive group for run and skip
    run_skip_group = parser.add_mutually_exclusive_group()
    run_skip_group.add_argument("--skip", nargs="+", choices=list(ALL_STEPS), 
                      help="Skip specific steps (use with --debug). Available steps: " + ", ".join(ALL_STEPS))
    run_skip_group.add_argument("--run", nargs="+", choices=list(ALL_STEPS),
                      help="Run only specific steps (inverse of --skip). Available steps: " + ", ".join(ALL_STEPS))
    
    args = parser.parse_args()
    
    if args.debug:
        set_debug_mode(True)
        
    if args.skip:
        if not args.debug:
            logger.warning("--skip flag requires --debug flag. Enabling debug mode automatically.")
            set_debug_mode(True)
        set_skip_steps(args.skip)
    
    if args.run:
        set_run_only_steps(args.run)
    
    seeds = None
    if args.seeds:
        seeds = [s.strip() for s in args.seeds.split(",") if s.strip()]
    
    if args.schedule:
        try:
            # Validate time format
            hour, minute = map(int, args.schedule.split(":"))
            if not (0 <= hour < 24 and 0 <= minute < 60):
                raise ValueError("Invalid time")
                
            logger.info(f"Scheduling workflow to run daily at {args.schedule}")
            schedule.every().day.at(args.schedule).do(scheduled_run, seeds=seeds, user_id=args.user, browser_type=args.browser)
            
            logger.info("Scheduler started. Press Ctrl+C to exit.")
            while True:
                schedule.run_pending()
                time.sleep(60)  # Check every minute
        except (ValueError, IndexError):
            logger.error("Invalid schedule time format. Use HH:MM (24-hour format)")
            sys.exit(1)
    else:
        # Run immediately
        success = run_workflow(seeds=seeds, user_id=args.user, browser_type=args.browser)
        sys.exit(0 if success else 1)

if __name__ == "__main__":
    main() 