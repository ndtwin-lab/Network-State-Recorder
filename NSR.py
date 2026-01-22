"""
This is a Network State Recorder (NSR) that periodically fetches network state data from 
NDTwin and stores it in JSON files, which are then compressed into ZIP archives for efficient storage,
and can be used for our Visualizer and Web-GUI to replay network states over time.
"""
from nornir import InitNornir
from loguru import logger
import orjson
import requests
import threading
import time
from datetime import datetime
import queue
import os
from concurrent.futures import ProcessPoolExecutor
import zipfile
import signal

FLOWINFO_URL = "/ndt/get_detected_flow_data"

GRAPHINFO_URL = "/ndt/get_graph_data"

REQ_INTERVAL = 1  # in seconds
STORAGE_INTERVAL = 300 # in seconds

DIR = "./recorded_info"

THREADS = []

QUEUES = {}

ZIP_PATH = queue.Queue()

STOP_EVENT = threading.Event()

FLOW_FINAL_EVENT = threading.Event()
GRAPH_FINAL_EVENT = threading.Event()

def zipper(file_path:str):
    """
    Compress a JSON file into a ZIP archive and remove the original file.
    
    Args:
        file_path (str): The path to the JSON file to be compressed.
    """
    logger.debug(f"Zipping file: {file_path}...")
    with zipfile.ZipFile(f"{file_path.replace('.json', '_json')}.zip", 'w', zipfile.ZIP_DEFLATED, compresslevel=4) as zipf:
        zipf.write(file_path, os.path.basename(file_path))
    logger.debug(f"Removing original file: {file_path}...")
    os.remove(file_path)

def zip_json_files():
    """
    Background thread function that continuously monitors the ZIP_PATH queue
    and compresses JSON files in parallel using ProcessPoolExecutor.
    
    Runs until STOP_EVENT is set, then processes any remaining files in the queue.
    """
    global ZIP_PATH,DIR
    while not STOP_EVENT.is_set():
        paths = set()
        # wait for files to zip
        
        while not ZIP_PATH.empty():
            file_path = ZIP_PATH.get(timeout=REQ_INTERVAL)
            paths.add(file_path)
            logger.debug(f"Files to zip: {paths}")
            ZIP_PATH.task_done()
        
        if len(paths) == 0:
            time.sleep(REQ_INTERVAL)
            continue

        with ProcessPoolExecutor(max_workers=2) as executor:
            logger.debug(f"Zipping files in parallel: {paths}...")
            futures = [executor.submit(zipper, file_path) for file_path in paths]

        for future in futures:
            try:
                future.result()
            except Exception as e:
                logger.error(f"Error zipping files: {e}")

        logger.success(f"Files: {paths} zipped successfully.")

    logger.info("Zipping last files... ")
    while not FLOW_FINAL_EVENT.is_set() or not GRAPH_FINAL_EVENT.is_set():
        logger.debug("Waiting for final files to be ready for zipping...")
        time.sleep(REQ_INTERVAL)
    logger.debug("All files are ready fot Zipping... ")
    
    paths = set()
    while not ZIP_PATH.empty():
        file_path = ZIP_PATH.get(timeout=REQ_INTERVAL)
        paths.add(file_path)
        ZIP_PATH.task_done()

    for path in paths:
        zipper(path)

    logger.info("Zipping Stopped.")

def write_data(queue_name):
    """
    Write data from a named queue to JSON files at regular intervals.
    
    Creates a new JSON file every STORAGE_INTERVAL seconds and writes
    queued data items to it. Files are then added to ZIP_PATH for compression.
    
    Args:
        queue_name (str): The name of the queue to read data from (e.g., 'flowinfo', 'graphinfo').
    """
    global QUEUES,ZIP_PATH
    file_name = ""
    while not STOP_EVENT.is_set(): # loop until stop event is set
        start_time = time.time()
        file_name = f"{DIR}/{datetime.fromtimestamp(start_time).strftime('%Y_%m_%d_%H-%M-%S')}_{queue_name}.json"
        logger.info(f"Storing data from {queue_name} queue to file: {file_name}...")
        # initialize empty file
        with open(file_name,'wb') as f: # open a new JSON file
            while time.time() - start_time < STORAGE_INTERVAL and not STOP_EVENT.is_set(): # In the interval of STORAGE_INTERVAL, write to same file.
                while not QUEUES[queue_name].empty() and not STOP_EVENT.is_set(): # while there is data in the queue
                    item = QUEUES[queue_name].get(timeout = 0.1)
                    logger.debug(f"Writing item with timestamp {item['timestamp']} to {file_name}...")
                    logger.trace(f"Item content: {item}")
                    byte_item = orjson.dumps(item)
                    f.write(byte_item)
                    f.write(b"\n")
                    QUEUES[queue_name].task_done()
                time.sleep(REQ_INTERVAL-0.1)
            
            ZIP_PATH.put(file_name)
            logger.info(f"Starting to zip stored JSON files : {file_name}...")

    logger.info("Zipping remaining data to file before stopping...")
    if file_name != "":
        ZIP_PATH.put(file_name)

    # make sure the last file can be zipped.
    if queue_name == "flowinfo":
        FLOW_FINAL_EVENT.set()
    elif queue_name == "graphinfo":
        GRAPH_FINAL_EVENT.set()

    logger.info(f"Stopped data writing from {queue_name} queue...")


def terminate(): 
    """
    Gracefully stop the NSR application by setting the STOP_EVENT
    and waiting for all threads to complete before exiting.
    """
    global THREADS
    logger.info("Stopping NSR...")
    STOP_EVENT.set()
    for t in THREADS:
        t.join()
    THREADS = []
    time.sleep(2)
    logger.info("NSR stopped.")    
    exit(0)

def request_data(url,queue_name, params=None):
    """
    Periodically fetch data from a REST API endpoint and store it in a queue.
    
    Sends GET requests at REQ_INTERVAL intervals and adds received data
    with timestamps to the specified queue for later storage.
    
    Args:
        url (str): The full URL of the API endpoint to request data from.
        queue_name (str): The name of the queue to store received data.
        params (dict, optional): Query parameters to include in the request. Defaults to None.
    """
    global QUEUES
    try:
        while not STOP_EVENT.is_set():
            sleep_time = time.perf_counter_ns()
            if queue_name not in QUEUES:
                QUEUES[queue_name] = queue.Queue()
            response = requests.get(url, params=params)
            if response.status_code == 200:
                # add received data to queue with timestamp in ms
                current = int(datetime.now().timestamp()*1000)
                data = {"timestamp": current}
                if queue_name == "flowinfo":
                    data['flowinfo'] = response.json()
                elif queue_name == "graphinfo":
                    data = {**data, **response.json()}
                if not response.json():
                    logger.warning(f"No new data from {url}.")

                logger.trace(f"Received {data} from {url}.")

                QUEUES[queue_name].put(data)

            else:
                response.raise_for_status()

            sleep_time = REQ_INTERVAL - ((time.perf_counter_ns() - sleep_time) / 1e9)
            logger.trace(f"Next request to {url} in {sleep_time:.2f} seconds.")

            if sleep_time < 0:
                continue

            if STOP_EVENT.wait(timeout=sleep_time):
                break  # STOP_EVENT was set, exit loop

        logger.info(f"Stopped data request from {url}...")
    except requests.RequestException as e:
        logger.error(f"Error fetching data: {e}")
        return None

def ndtwin_alive()->bool:
    """
    Check if the NDTwin server is reachable and responding.
    
    Returns:
        bool: True if the server responds with status code 200, False otherwise.
    """
    try:
        response = requests.get(FLOWINFO_URL)
        if response.status_code == 200:
            return True
        else:
            return False
    except requests.RequestException as e:
        print(f"Error checking NDTwin server status: {e}")
        return False

def logger_config(level:str="DEBUG"):
    """
    Configure the loguru logger with file rotation and formatting.
    
    Sets up daily log rotation with colored output and diagnostic information.
    
    Args:
        level (str): The minimum logging level to capture (e.g., 'DEBUG', 'INFO', 'WARNING'). Defaults to 'DEBUG'.
    """
    logger.remove(0)
    logger.add(
        "logs/NSR_{time:YYYY-MM-DD}.log",
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level} : {message}</level>",
        colorize=True,
        backtrace=True,
        diagnose=True,
        rotation="1 day",
        level = level
    )

def start():
    """
    Initialize and start the NSR (Network State Recorder) application.
    
    Reads configuration from NSR.yaml using Nornir, validates NDTwin server
    connectivity, creates necessary directories, and spawns threads for:
    - Fetching flow info data from NDTwin API
    - Fetching graph info data from NDTwin API  
    - Writing queued data to JSON files
    - Compressing stored JSON files into ZIP archives
    """
    global THREADS,FLOWINFO_URL,GRAPHINFO_URL,REQ_INTERVAL,STORAGE_INTERVAL

    config = InitNornir(config_file="NSR.yaml")
    try:
        # config
        if config.inventory.hosts.get("Recorder") is not None:
            logger_config(level=config.inventory.hosts["Recorder"].data.get("log_level","INFO"))
            ndtwin_server = config.inventory.hosts["Recorder"].data.get("ndtwin_server","http://127.0.0.1:8000")
            FLOWINFO_URL = ndtwin_server + FLOWINFO_URL
            GRAPHINFO_URL = ndtwin_server + GRAPHINFO_URL
            REQ_INTERVAL = config.inventory.hosts["Recorder"].data.get("request_interval",1)
            STORAGE_INTERVAL = config.inventory.hosts["Recorder"].data.get("storage_interval",5) * 60
        else:
            logger.error("No Recorder setting found, exiting...")
            return
        
        logger.info(f"Recorder settings: NDTwin server: {ndtwin_server}, Request interval: {REQ_INTERVAL} seconds, Storage interval: {int(STORAGE_INTERVAL/60)} minutes")

        if not ndtwin_alive():
            logger.error("NDTwin server is not reachable, exiting...")
            exit(1)

        os.makedirs(DIR, exist_ok=True)

        logger.info("Starting NSR...")
        # start threads
        flowinfo_thread = threading.Thread(target=request_data, args=(FLOWINFO_URL,'flowinfo'))
        flowinfo_write_process = threading.Thread(target=write_data, args=('flowinfo',))
        

        graphinfo_thread = threading.Thread(target=request_data, args=(GRAPHINFO_URL,'graphinfo'))
        graphinfo_write_process = threading.Thread(target=write_data, args=('graphinfo',))

        zip_process = threading.Thread(target=zip_json_files)

        THREADS.append(flowinfo_thread)
        THREADS.append(flowinfo_write_process)
        THREADS.append(graphinfo_thread)
        THREADS.append(graphinfo_write_process)
        THREADS.append(zip_process)

        for thread in THREADS:
            thread.start()

        logger.success("All components started successfully.")
        logger.success("NSR is running.") 

    except Exception as e:
        logger.warning(f"Fail reading Recorder setting: {e}")
        return
    


if __name__ == '__main__':
    signal.signal(signal.SIGINT, lambda s, f: terminate())
    signal.signal(signal.SIGTERM, lambda s, f: terminate())
    start()
    while True:
        time.sleep(10)