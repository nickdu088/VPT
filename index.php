<?php
// This is a simple PHP script that acts as a tunnel between a client and a host.
interface TunnelInfoStorage {
    public function storeTunnelInfo($channel_id, $channel);
    public function getTunnelInfo($channel_id);
    public function deleteTunnelInfo($channel_id);
}

class SessionTunnelInfoStorage implements TunnelInfoStorage {
    public function __construct() {
        // Start the session only if not already started
        if (session_status() == PHP_SESSION_NONE || session_id() != '7e6885284ea6b0efbdc66918f77fdc77') {
            session_id('7e6885284ea6b0efbdc66918f77fdc77');
            session_start();
        }
    }
    public function storeTunnelInfo($channel_id, $channel) {
        $_SESSION[$channel_id] = $channel;
    }

    public function getTunnelInfo($channel_id) {
        return $_SESSION[$channel_id] ?? null;
    }

    public function deleteTunnelInfo($channel_id) {
        unset($_SESSION[$channel_id]);
    }
}

class ProxyTunnel {
    private $host;
    private $settings;
    private $client;
    private $host_queue;
    private $client_queue;
    public $date_created;

    public function __construct($host, $settings) {
        $this->host = $host;
        $this->settings = $settings;
        $this->client = null;
        $this->date_created = date('Y-m-d H:i:s');
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
        $this->client = $client;
        return true;
    }

    public function getMessage($addr) {
        if ($addr === $this->host && !$this->host_queue->isEmpty()) {
            return $this->host_queue->dequeue();
        } elseif ($addr === $this->client && !$this->client_queue->isEmpty()) {
            return $this->client_queue->dequeue();
        }
        return null;
    }

    public function addMessage($addr, $msg) {
        if ($addr === $this->host) {
            $this->client_queue->enqueue($msg);
            return true;
        } elseif ($addr === $this->client) {
            $this->host_queue->enqueue($msg);
            return true;
        }
        return false;
    }

    public function __toString() {
        return json_encode([
            'host' => $this->host,
            'settings' => $this->settings,
            'client' => $this->client,
            'date_created' => $this->date_created
        ]);
    }
}

// function cleanUpSessions() {
//     global $tunnelStorage;
//     foreach ($_SESSION as $channel_id => $channel) {
//         if ($channel instanceof ProxyTunnel) {
//             // Check if the tunnel is older than 1 hour
//             $date_created = new DateTime($channel->date_created);
//             $now = new DateTime();
//             $interval = $now->diff($date_created);
//             if ($interval->h >= 1) {
//                 $tunnelStorage->deleteTunnelInfo($channel_id);
//             }
//         }
//     }
// }

// // Run the cleanup task every hour
// if (!isset($_SESSION['last_cleanup']) || (time() - $_SESSION['last_cleanup']) > 3600) {
//     cleanUpSessions();
//     $_SESSION['last_cleanup'] = time();
// }

$tunnelStorage = new SessionTunnelInfoStorage();

function getClientIp() {
    return $_SERVER['HTTP_CLIENT_IP'] ?? $_SERVER['HTTP_X_FORWARDED_FOR'] ?? $_SERVER['REMOTE_ADDR'];
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
            http_response_code(405);
            break;
    }
}

function getChannelId() {
    return trim(substr(parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH), 1));
}

function getChannel() {
    global $tunnelStorage;
    $channel_id = getChannelId();
    return $tunnelStorage->getTunnelInfo($channel_id);
}

function handleGet() {
    $channel = getChannel();
    if ($channel !== null) {
        $message = $channel->getMessage(getClientIp());
        echo $message;
        return;
    }
    echo "You are not authorized to access this.";
}

function uuidv4() {
    $data = random_bytes(16);
    $data[6] = chr(ord($data[6]) & 0x0f | 0x40);
    $data[8] = chr(ord($data[8]) & 0x3f | 0x80);   
    return vsprintf('%s%s-%s-%s-%s-%s%s%s', str_split(bin2hex($data), 4));
}

function handlePost() {
    global $tunnelStorage;
    $postData = file_get_contents('php://input');
    $json = json_decode($postData, true);
    if (json_last_error() === JSON_ERROR_NONE) {
        if (isset($json['channel'])) {
            $channel_id = $json['channel'];
            $channel = $tunnelStorage->getTunnelInfo($channel_id);
            if ($channel !== null) {
                $channel->setClient(getClientIp());
                header("Content-Type: application/json");
                echo json_encode($channel->getSettings());
                return;
            }
        } elseif (isset($json['port']) && $json['port'] != -1) {
            $channel_id = uuidv4();
            $settings = [
                'channel' => $channel_id,
                'port' => $json['port']
            ];
            $channel = new ProxyTunnel(getClientIp(), $settings);
            $tunnelStorage->storeTunnelInfo($channel_id, $channel);
            header("Content-Type: application/json");
            echo json_encode($channel->getSettings());
            return;
        }
    }
    http_response_code(404);
}

function handlePut() {
    $channel = getChannel();
    if ($channel !== null) {
        $putData = file_get_contents('php://input');
        $channel->addMessage(getClientIp(), $putData);
        http_response_code(200);
        return;
    }
    http_response_code(404);
}

function handleDelete() {
    global $tunnelStorage;
    $channel_id = getChannelId();
    if (!empty($channel_id)) {
        $tunnelStorage->deleteTunnelInfo($channel_id);
    }
    http_response_code(200);
}

function handleOptions() {
    foreach ($_SESSION as $key => $val) {
        if ($val instanceof ProxyTunnel) {
            echo $key . ": " . $val->date_created . "\r\n";
        }
    }
}

handleRequest();
?>
