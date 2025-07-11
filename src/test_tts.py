import pyttsx3
import logging

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

try:
    engine = pyttsx3.init()
    logging.info("pyttsx3 engine initialized successfully.")

    # Get current rate and volume
    rate = engine.getProperty('rate')
    volume = engine.getProperty('volume')
    voices = engine.getProperty('voices')

    logging.debug(f"Current speech rate: {rate}")
    logging.debug(f"Current volume: {volume}")
    logging.debug(f"Available voices: {len(voices)}")
    for i, voice in enumerate(voices):
        logging.debug(f"  Voice {i}: ID={voice.id}, Name={voice.name}, Lang={voice.languages}, Gender={voice.gender}")
        # Optionally set a different voice if available (e.g., voices[0].id)
        # engine.setProperty('voice', voices[0].id) 

    test_text = "Hello, this is a test of the text to speech functionality."
    engine.say(test_text)
    logging.info(f"Attempting to speak: '{test_text}'")
    engine.runAndWait()
    logging.info("Speech completed.")
    engine.stop()
    logging.info("Engine stopped.")

except ImportError:
    logging.error("pyttsx3 not found. Please install it using 'pip install pyttsx3'.")
except Exception as e:
    logging.critical(f"An error occurred with pyttsx3: {e}", exc_info=True)

print("Test script finished.")