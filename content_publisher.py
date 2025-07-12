#!/usr/bin/env python3
"""
Content Publisher

This script handles the content creation workflow:
1. Generate keywords (using provided seeds or defaults)
2. Create content for the top keyword
3. Publish to Medium

Usage:
    python content_publisher.py [--seeds SEED1,SEED2,...] [--schedule HH:MM] [--debug]

Example:
    python content_publisher.py --seeds "contract lifecycle management, smart contracts"
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
    _publish_medium_dynamic as publish_medium_func
)
from core import global_cfg
from core.medium import get_unpublished_filenames
from dotenv import load_dotenv
from Utils.google_drive import add_new_article_entry, update_medium_article

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("content_publisher.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("content_publisher")

# Load environment variables and configuration
load_dotenv()
global_config = global_cfg()
DEFAULT_KEYWORDS_PATH = global_config["keywords_file"]
KEYWORDS_JSON_PATH = DEFAULT_KEYWORDS_PATH  # Will be changed if seeds are provided

# Global variables
CURRENT_KEYWORD = None
DEBUG_MODE = False
SKIP_STEPS: Set[str] = set()
RUN_ONLY_STEPS: Set[str] = set()

# Define workflow steps
STEP_GENERATE_KEYWORDS = "generate_keywords"
STEP_CREATE_CONTENT = "create_content"
STEP_PUBLISH_MEDIUM = "publish_medium"

ALL_STEPS = {
    STEP_GENERATE_KEYWORDS,
    STEP_CREATE_CONTENT,
    STEP_PUBLISH_MEDIUM
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

def run_workflow(seeds: Optional[List[str]] = None, browser_type: str = "chromium") -> bool:
    """
    Run the content creation workflow.
    
    Args:
        seeds: Optional list of seed words for keyword generation
        browser_type: Browser to use for Medium publishing ("chromium" or "firefox")
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        logger.info("=" * 60)
        logger.info("STARTING CONTENT CREATION WORKFLOW")
        logger.info("=" * 60)
        
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
            
            # Extract filename and add to tracking sheet
            try:
                filename = content_result.get("filename", "")
                if filename:
                    article_id = add_new_article_entry(filename, keyword)
                    logger.info(f"Added article entry with ID {article_id}")
            except Exception as e:
                logger.error(f"Failed to add article entry: {e}")
        
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
            medium_result = publish_medium_func(filename, browser_type)
            
            if "error" in medium_result or medium_result.get("status") == "error":
                logger.error(f"Medium publishing failed: {medium_result}")
                return False
                
            logger.info("Published to Medium successfully")
            
            # Update tracking with Medium URL
            try:
                medium_url = medium_result.get("url", "")
                if medium_url:
                    update_medium_article(filename, {
                        "medium_url": medium_url,
                        "posted_medium": True,
                        "date": datetime.now().strftime("%Y-%m-%d")
                    })
                    logger.info(f"Updated article entry with Medium URL: {medium_url}")
            except Exception as e:
                logger.error(f"Failed to update article entry: {e}")
        
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

def scheduled_run(seeds: Optional[List[str]] = None):
    """Function to be called by the scheduler."""
    logger.info(f"Running scheduled workflow at {datetime.now().strftime('%H:%M:%S')}")
    run_workflow(seeds)

def main():
    parser = argparse.ArgumentParser(description="Content Publisher Tool")
    parser.add_argument("--seeds", help="Comma-separated list of seed words for keyword generation")
    parser.add_argument("--schedule", help="Schedule time in HH:MM format (24-hour)")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode with verbose logging")
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
            schedule.every().day.at(args.schedule).do(run_workflow, seeds=seeds, browser_type=args.browser)
            
            logger.info("Scheduler started. Press Ctrl+C to exit.")
            while True:
                schedule.run_pending()
                time.sleep(60)  # Check every minute
        except (ValueError, IndexError):
            logger.error("Invalid schedule time format. Use HH:MM (24-hour format)")
            sys.exit(1)
    else:
        # Run immediately
        success = run_workflow(seeds=seeds, browser_type=args.browser)
        sys.exit(0 if success else 1)

if __name__ == "__main__":
    main() 