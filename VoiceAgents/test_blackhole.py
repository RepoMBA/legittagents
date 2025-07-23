#!/usr/bin/env python3
"""
Test BlackHole audio configuration
"""
import sounddevice as sd
import logging

def test_blackhole_setup():
    """Test if BlackHole is properly configured"""
    print("🎧 Testing BlackHole Audio Configuration")
    print("=" * 50)
    
    devices = sd.query_devices()
    blackhole_devices = []
    
    for i, device in enumerate(devices):
        if 'blackhole' in device['name'].lower():
            blackhole_devices.append((i, device))
            is_input = device['max_input_channels'] > 0
            is_output = device['max_output_channels'] > 0
            
            print(f"✅ Found: {device['name']}")
            print(f"   ID: {i}")
            print(f"   Input Channels: {device['max_input_channels']}")
            print(f"   Output Channels: {device['max_output_channels']}")
            print(f"   Sample Rate: {device['default_samplerate']}")
            print(f"   Can be used as: {'Input ' if is_input else ''}{'Output' if is_output else ''}")
            print()
    
    if blackhole_devices:
        print("🎯 BlackHole Status: READY")
        print("Your agents should now be able to hear each other!")
        
        # Check default devices
        try:
            default_input = sd.query_devices(kind='input')
            default_output = sd.query_devices(kind='output')
            
            print(f"Current Default Input: {default_input['name']}")
            print(f"Current Default Output: {default_output['name']}")
            
            if 'blackhole' in default_input['name'].lower() and 'blackhole' in default_output['name'].lower():
                print("✅ Both input and output are set to BlackHole - Perfect!")
            else:
                print("⚠️  Recommendation: Set both input and output to BlackHole for best results")
        except Exception as e:
            print(f"Could not check default devices: {e}")
            
    else:
        print("❌ BlackHole Status: NOT FOUND")
        print("Please install BlackHole from: https://github.com/ExistentialAudio/BlackHole")
    
    return len(blackhole_devices) > 0

if __name__ == "__main__":
    test_blackhole_setup()
