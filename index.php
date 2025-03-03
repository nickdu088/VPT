<?php
// Start the session
if (session_status() == PHP_SESSION_NONE || session_id() != '7e6885284ea6b0efbdc66918f77fdc77') {
    session_id('7e6885284ea6b0efbdc66918f77fdc77');
    session_start();
}

class ProxyChannel {
    private $host;
    private $settings;
    private $client;
    private $host_queue;
    private $client_queue;

    public function __construct($host, $settings) {
        $this->host = $host;
        $this->settings = $settings;
        $this->client = null;
        $this->host_queue = new SplQueue();
        $this->client_queue = new SplQueue();
    }

    public function getSettings() {
        return $this->settings;
    }

    public function setSettings($settings) {
        $this->settings = $settings;
    }

    public function setClient($client) {
        //if ($this->client == null) {
            $this->client = $client;
            return true;
        //} 
        //return false;
    }

    public function getMessage($addr) {
        if ($addr == $this->host && !$this->host_queue->isEmpty()) {
            return $this->host_queue->dequeue();
        } else if ($addr == $this->client && !$this->client_queue->isEmpty()) {
            return $this->client_queue->dequeue();
        }
        return null;
    }

    public function addMessage($addr, $msg) {
        if ($addr == $this->host) {
            $this->client_queue->enqueue($msg);
            return true;
        } else if ($addr == $this->client) {
            $this->host_queue->enqueue($msg);
            return true;
        }
        return false;
    }
}

function getClientIp() {
    if (!empty($_SERVER['HTTP_CLIENT_IP'])) {
        return $_SERVER['HTTP_CLIENT_IP'];
    } elseif (!empty($_SERVER['HTTP_X_FORWARDED_FOR'])) {
        return $_SERVER['HTTP_X_FORWARDED_FOR'];
    } else {
        return $_SERVER['REMOTE_ADDR'];
    }
}

function handleRequest() {

    $method = $_SERVER['REQUEST_METHOD'];

    switch ($method) {
        case 'GET':
            handleGet();
            break;
        case 'POST':
            handlePost();
            break;
        case 'PUT':
            handlePut();
            break;
        case 'DELETE':
            handleDelete();
            break;
        case 'OPTIONS':
            handleOptions();
            break;
        default:
            header("HTTP/1.0 405 Method Not Allowed");
            break;
    }
}

function getChannelId() {
    $channel_id = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);
    $channel_id = trim(substr($channel_id, 1));
    return $channel_id;
}

function getChannel() {
    $channel_id = getChannelId();
    if (!empty($channel_id) && isset($_SESSION[$channel_id])) {
        return $_SESSION[$channel_id];
    }
    return null;
}

function handleGet() {
    $channel = getChannel();
    if ($channel != null) {
        $message = $channel->getMessage(getClientIp());
        echo $message;
        return;
    }

    header("HTTP/1.0 404 Not Found");
}

function uuidv4() {
    $data = random_bytes(16);
    $data[6] = chr(ord($data[6]) & 0x0f | 0x40); // set version to 0100
    $data[8] = chr(ord($data[8]) & 0x3f | 0x80); // set bits 6-7 to 10
    
    return vsprintf('%s%s-%s-%s-%s-%s%s%s', str_split(bin2hex($data), 4));
}

function handlePost() {
    // Handle POST request
    $postData = file_get_contents('php://input');
    $json = json_decode($postData, true);
    if (json_last_error() === JSON_ERROR_NONE) {
        if (isset($json['channel']) && !is_null($json['channel'])) {
            $channel_id = $json['channel'];
            if (isset($_SESSION[$channel_id])) {
                $channel = $_SESSION[$channel_id];
                $channel->setClient(getClientIp());
                header("Content-Type: application/json");
                echo json_encode($channel->getSettings());
                return;
            }
        } else if (isset($json['port']) && $json['port'] != -1) {
            $channel_id = uuidv4();
            $settings = [
                'channel' => $channel_id,
                'port' => $json['port']
            ];
            $channel = new ProxyChannel(getClientIp(), $settings);
            $_SESSION["$channel_id"] = $channel;
            header("Content-Type: application/json");
            echo json_encode($channel->getSettings());
            return;
        }
    }
    header("HTTP/1.0 400 Bad Request");
}

function handlePut() {
    $channel = getChannel();
    if ($channel != null) {
        $putData = file_get_contents('php://input');
        $channel->addMessage(getClientIp(), $putData);
        header("HTTP/1.0 200 OK");
        return;
    }
    header("HTTP/1.0 404 Not Found");
}

function handleDelete() {
    $channel_id = getChannelId();
    if (!empty($channel_id)) {
        unset($_SESSION[$channel_id]);
    }
    header("HTTP/1.0 200 OK");
}

function handleOptions() {
    foreach ($_SESSION as $key=>$val)
        echo $key."\r\n";
}

handleRequest();

?>
