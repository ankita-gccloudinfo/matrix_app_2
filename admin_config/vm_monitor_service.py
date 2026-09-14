import os
import psutil
import time
import json
import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from collections import deque
from pathlib import Path
import subprocess
import threading

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import uvicorn
import asyncio

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MetricsDatabase:
    """SQLite database for metrics storage with auto-cleanup"""

    def __init__(self, db_path: str = './monitor_data/metrics.db'):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(exist_ok=True)
        self.conn = None
        self._init_database()

        # Start cleanup thread
        self.cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self.cleanup_thread.start()

    def _init_database(self):
        """Initialize database schema"""
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row

        cursor = self.conn.cursor()

        # Set timezone to UTC for consistent storage
        cursor.execute("PRAGMA timezone = 'UTC'")

        # Main metrics table
        cursor.execute('''
                       CREATE TABLE IF NOT EXISTS metrics (
                                                              id INTEGER PRIMARY KEY AUTOINCREMENT,
                                                              timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                                                              cpu_percent REAL,
                                                              cpu_load_1min REAL,
                                                              cpu_load_5min REAL,
                                                              cpu_load_15min REAL,
                                                              memory_percent REAL,
                                                              memory_used_gb REAL,
                                                              memory_available_gb REAL,
                                                              swap_percent REAL,
                                                              gpu_utilization REAL,
                                                              gpu_memory_percent REAL,
                                                              gpu_memory_used_gb REAL,
                                                              gpu_temperature REAL,
                                                              gpu_power_draw REAL,
                                                              disk_percent REAL,
                                                              disk_read_mb REAL,
                                                              disk_write_mb REAL,
                                                              network_sent_gb REAL,
                                                              network_recv_gb REAL,
                                                              vllm_running BOOLEAN,
                                                              vllm_cpu_percent REAL,
                                                              vllm_memory_mb REAL,
                                                              mysql_running BOOLEAN,
                                                              mysql_connections INTEGER
                       )
                       ''')

        # Create index on timestamp for faster queries
        cursor.execute('''
                       CREATE INDEX IF NOT EXISTS idx_timestamp
                           ON metrics(timestamp DESC)
                       ''')

        # Alerts table
        cursor.execute('''
                       CREATE TABLE IF NOT EXISTS alerts (
                                                             id INTEGER PRIMARY KEY AUTOINCREMENT,
                                                             timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                                                             level TEXT,
                                                             component TEXT,
                                                             message TEXT
                       )
                       ''')

        cursor.execute('''
                       CREATE INDEX IF NOT EXISTS idx_alerts_timestamp
                           ON alerts(timestamp DESC)
                       ''')

        # Speed test table - internet download/upload/ping results.
        # These are only inserted when a speed test is explicitly run
        # (they are NOT part of the 2s metrics polling loop).
        cursor.execute('''
                       CREATE TABLE IF NOT EXISTS speedtests (
                                                             id INTEGER PRIMARY KEY AUTOINCREMENT,
                                                             timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                                                             download_mbps REAL,
                                                             upload_mbps REAL,
                                                             ping_ms REAL,
                                                             server_name TEXT,
                                                             server_location TEXT
                       )
                       ''')

        cursor.execute('''
                       CREATE INDEX IF NOT EXISTS idx_speedtests_timestamp
                           ON speedtests(timestamp DESC)
                       ''')

        self.conn.commit()

        # Log current data size
        cursor.execute('SELECT COUNT(*) as count FROM metrics')
        count = cursor.fetchone()[0]
        logger.info(f"Database initialized with {count} existing records")

    def insert_metrics(self, metrics: Dict[str, Any]):
        """Insert a metrics record"""
        try:
            cursor = self.conn.cursor()

            # Use explicit timestamp from metrics or current time
            timestamp = metrics.get('timestamp', datetime.now().isoformat())

            # Extract GPU metrics
            gpu = metrics.get('gpu', {})
            gpu_data = gpu.get('gpus', [{}])[0] if gpu.get('available') else {}

            # Extract disk metrics
            disk = metrics.get('disk', {})
            disk_percent = disk.get('partitions', [{}])[0].get('percent', 0) if disk.get('partitions') else 0
            disk_io = disk.get('io', {})

            # Extract network metrics
            network = metrics.get('network', {})

            # Extract process metrics
            vllm = metrics.get('vllm', {})
            vllm_proc = vllm.get('processes', [{}])[0] if vllm.get('processes') else {}

            mysql = metrics.get('mysql', {})
            mysql_proc = mysql.get('processes', [{}])[0] if mysql.get('processes') else {}

            cursor.execute('''
                           INSERT INTO metrics (
                               timestamp,
                               cpu_percent, cpu_load_1min, cpu_load_5min, cpu_load_15min,
                               memory_percent, memory_used_gb, memory_available_gb, swap_percent,
                               gpu_utilization, gpu_memory_percent, gpu_memory_used_gb,
                               gpu_temperature, gpu_power_draw,
                               disk_percent, disk_read_mb, disk_write_mb,
                               network_sent_gb, network_recv_gb,
                               vllm_running, vllm_cpu_percent, vllm_memory_mb,
                               mysql_running, mysql_connections
                           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                           ''', (
                               timestamp,
                               metrics['cpu'].get('percent', 0),
                               metrics['cpu'].get('load_1min', 0),
                               metrics['cpu'].get('load_5min', 0),
                               metrics['cpu'].get('load_15min', 0),
                               metrics['memory'].get('percent', 0),
                               metrics['memory'].get('used_gb', 0),
                               metrics['memory'].get('available_gb', 0),
                               metrics['memory'].get('swap_percent', 0),
                               gpu_data.get('utilization', 0),
                               gpu_data.get('memory_percent', 0),
                               gpu_data.get('memory_used_gb', 0),
                               gpu_data.get('temperature', 0),
                               gpu_data.get('power_draw', 0),
                               disk_percent,
                               disk_io.get('read_mb', 0),
                               disk_io.get('write_mb', 0),
                               network.get('bytes_sent_gb', 0),
                               network.get('bytes_recv_gb', 0),
                               vllm.get('found', False),
                               vllm_proc.get('cpu_percent', 0),
                               vllm_proc.get('memory_mb', 0),
                               mysql.get('found', False),
                               mysql_proc.get('connections', 0)
                           ))

            self.conn.commit()

        except Exception as e:
            logger.error(f"Failed to insert metrics: {e}")

    def insert_alert(self, level: str, component: str, message: str):
        """Insert an alert"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                           INSERT INTO alerts (level, component, message)
                           VALUES (?, ?, ?)
                           ''', (level, component, message))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Failed to insert alert: {e}")

    def insert_speedtest(self, result: Dict[str, Any]):
        """Insert an internet speed test result"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                           INSERT INTO speedtests (
                               download_mbps, upload_mbps, ping_ms, server_name, server_location
                           ) VALUES (?, ?, ?, ?, ?)
                           ''', (
                               result.get('download_mbps', 0),
                               result.get('upload_mbps', 0),
                               result.get('ping_ms', 0),
                               result.get('server_name', ''),
                               result.get('server_location', '')
                           ))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Failed to insert speedtest: {e}")

    def get_latest_speedtest(self) -> Optional[Dict]:
        """Get the most recent speed test result"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                           SELECT * FROM speedtests
                           ORDER BY timestamp DESC
                               LIMIT 1
                           ''')
            row = cursor.fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"Failed to get latest speedtest: {e}")
            return None

    def get_speedtest_history(self, limit: int = 50) -> List[Dict]:
        """Get recent speed test results"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                           SELECT * FROM speedtests
                           ORDER BY timestamp DESC
                               LIMIT ?
                           ''', (limit,))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Failed to get speedtest history: {e}")
            return []

    def get_recent_metrics(self, minutes: int = 5) -> List[Dict]:
        """Get metrics from last N minutes"""
        try:
            cursor = self.conn.cursor()
            cutoff = datetime.now() - timedelta(minutes=minutes)

            cursor.execute('''
                           SELECT * FROM metrics
                           WHERE timestamp > ?
                           ORDER BY timestamp ASC
                           ''', (cutoff,))

            rows = cursor.fetchall()
            return [dict(row) for row in rows]

        except Exception as e:
            logger.error(f"Failed to get recent metrics: {e}")
            return []

    def get_metrics_range(self, hours: int = 24) -> List[Dict]:
        """Get metrics for specified time range"""
        try:
            cursor = self.conn.cursor()
            cutoff = datetime.now() - timedelta(hours=hours)

            cursor.execute('''
                           SELECT * FROM metrics
                           WHERE timestamp > ?
                           ORDER BY timestamp ASC
                           ''', (cutoff,))

            rows = cursor.fetchall()
            return [dict(row) for row in rows]

        except Exception as e:
            logger.error(f"Failed to get metrics range: {e}")
            return []

    def get_metrics_summary(self, hours: int = 24) -> Dict[str, Any]:
        """Get statistical summary for time range"""
        try:
            cursor = self.conn.cursor()
            cutoff = datetime.now() - timedelta(hours=hours)

            cursor.execute('''
                           SELECT
                               COUNT(*) as count,
                    MIN(cpu_percent) as cpu_min,
                    AVG(cpu_percent) as cpu_avg,
                    MAX(cpu_percent) as cpu_max,
                    MIN(memory_percent) as mem_min,
                    AVG(memory_percent) as mem_avg,
                    MAX(memory_percent) as mem_max,
                    MIN(gpu_utilization) as gpu_util_min,
                    AVG(gpu_utilization) as gpu_util_avg,
                    MAX(gpu_utilization) as gpu_util_max,
                    MIN(gpu_memory_percent) as gpu_mem_min,
                    AVG(gpu_memory_percent) as gpu_mem_avg,
                    MAX(gpu_memory_percent) as gpu_mem_max
                           FROM metrics
                           WHERE timestamp > ?
                           ''', (cutoff,))

            row = cursor.fetchone()
            return dict(row) if row else {}

        except Exception as e:
            logger.error(f"Failed to get metrics summary: {e}")
            return {}

    def get_recent_alerts(self, limit: int = 20) -> List[Dict]:
        """Get recent alerts"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                           SELECT * FROM alerts
                           ORDER BY timestamp DESC
                               LIMIT ?
                           ''', (limit,))

            rows = cursor.fetchall()
            return [dict(row) for row in rows]

        except Exception as e:
            logger.error(f"Failed to get alerts: {e}")
            return []

    def cleanup_old_data(self):
        """Delete data older than 7 days"""
        try:
            cursor = self.conn.cursor()
            cutoff = datetime.now() - timedelta(days=7)

            # Delete old metrics
            cursor.execute('DELETE FROM metrics WHERE timestamp < ?', (cutoff,))
            metrics_deleted = cursor.rowcount

            # Delete old alerts
            cursor.execute('DELETE FROM alerts WHERE timestamp < ?', (cutoff,))
            alerts_deleted = cursor.rowcount

            # Delete old speedtests
            cursor.execute('DELETE FROM speedtests WHERE timestamp < ?', (cutoff,))
            speedtests_deleted = cursor.rowcount

            self.conn.commit()

            # Vacuum to reclaim space
            cursor.execute('VACUUM')

            if metrics_deleted > 0 or alerts_deleted > 0 or speedtests_deleted > 0:
                logger.info(f"Cleanup: Deleted {metrics_deleted} metrics, {alerts_deleted} alerts, {speedtests_deleted} speedtests")

        except Exception as e:
            logger.error(f"Failed to cleanup old data: {e}")

    def _cleanup_loop(self):
        """Background thread to cleanup old data every hour"""
        while True:
            time.sleep(3600)  # Run every hour
            self.cleanup_old_data()

    def get_database_stats(self) -> Dict[str, Any]:
        """Get database statistics"""
        try:
            cursor = self.conn.cursor()

            # Count records
            cursor.execute('SELECT COUNT(*) as count FROM metrics')
            metrics_count = cursor.fetchone()[0]

            cursor.execute('SELECT COUNT(*) as count FROM alerts')
            alerts_count = cursor.fetchone()[0]

            # Get date range
            cursor.execute('SELECT MIN(timestamp) as first, MAX(timestamp) as last FROM metrics')
            row = cursor.fetchone()

            # Get database file size
            db_size_mb = self.db_path.stat().st_size / (1024 * 1024) if self.db_path.exists() else 0

            return {
                'metrics_count': metrics_count,
                'alerts_count': alerts_count,
                'first_record': row[0] if row else None,
                'last_record': row[1] if row else None,
                'database_size_mb': round(db_size_mb, 2)
            }

        except Exception as e:
            logger.error(f"Failed to get database stats: {e}")
            return {}

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()


class SystemMonitor:
    """Monitor all system resources with SQLite storage"""

    def __init__(self, db_path: str = './monitor_data/metrics.db'):
        self.db = MetricsDatabase(db_path)
        self.gpu_available = self._check_gpu_available()
        self.last_network_io = None
        # Prevent overlapping speed tests (they take 10-20s and saturate the link)
        self.speedtest_lock = threading.Lock()
        self.speedtest_running = False

    def _check_gpu_available(self) -> bool:
        """Check if nvidia-smi is available"""
        try:
            subprocess.run(['nvidia-smi'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return True
        except FileNotFoundError:
            logger.warning("nvidia-smi not found - GPU monitoring disabled")
            return False

    def get_cpu_metrics(self) -> Dict[str, Any]:
        """Get CPU usage metrics"""
        try:
            cpu_percent = psutil.cpu_percent(interval=0.5, percpu=False)
            cpu_per_core = psutil.cpu_percent(interval=0.5, percpu=True)
            cpu_freq = psutil.cpu_freq()
            load_avg = psutil.getloadavg()
            cpu_count = psutil.cpu_count()

            return {
                'percent': round(cpu_percent, 2),
                'per_core': [round(c, 2) for c in cpu_per_core],
                'count': cpu_count,
                'load_1min': round(load_avg[0], 2),
                'load_5min': round(load_avg[1], 2),
                'load_15min': round(load_avg[2], 2),
                'frequency_current': round(cpu_freq.current, 2) if cpu_freq else None,
                'frequency_max': round(cpu_freq.max, 2) if cpu_freq else None,
                'status': self._get_status(cpu_percent, 70, 90)
            }
        except Exception as e:
            logger.error(f"CPU metrics error: {e}")
            return {'error': str(e)}

    def get_memory_metrics(self) -> Dict[str, Any]:
        """Get RAM usage metrics"""
        try:
            mem = psutil.virtual_memory()
            swap = psutil.swap_memory()

            return {
                'total_gb': round(mem.total / (1024**3), 2),
                'used_gb': round(mem.used / (1024**3), 2),
                'available_gb': round(mem.available / (1024**3), 2),
                'percent': round(mem.percent, 2),
                'swap_total_gb': round(swap.total / (1024**3), 2),
                'swap_used_gb': round(swap.used / (1024**3), 2),
                'swap_percent': round(swap.percent, 2),
                'status': self._get_status(mem.percent, 80, 95)
            }
        except Exception as e:
            logger.error(f"Memory metrics error: {e}")
            return {'error': str(e)}

    def get_gpu_metrics(self) -> Dict[str, Any]:
        """Get GPU metrics using nvidia-smi"""
        if not self.gpu_available:
            return {'available': False, 'message': 'No GPU detected'}

        try:
            query = 'index,name,utilization.gpu,utilization.memory,memory.total,memory.used,memory.free,temperature.gpu,power.draw,power.limit,pstate,clocks.current.graphics'

            result = subprocess.run(
                ['nvidia-smi', f'--query-gpu={query}', '--format=csv,noheader,nounits'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            if result.returncode != 0:
                return {'available': False, 'error': result.stderr}

            lines = result.stdout.strip().split('\n')
            gpus = []

            for line in lines:
                values = [v.strip() for v in line.split(',')]
                if len(values) >= 12:
                    mem_total_mb = float(values[4])
                    mem_used_mb = float(values[5])

                    gpu_data = {
                        'index': int(values[0]),
                        'name': values[1],
                        'utilization': float(values[2]),
                        'memory_utilization': float(values[3]),
                        'memory_total_gb': round(mem_total_mb / 1024, 2),
                        'memory_used_gb': round(mem_used_mb / 1024, 2),
                        'memory_free_gb': round(float(values[6]) / 1024, 2),
                        'memory_percent': round((mem_used_mb / mem_total_mb) * 100, 2),
                        'temperature': float(values[7]),
                        'power_draw': float(values[8]),
                        'power_limit': float(values[9]),
                        'power_percent': round((float(values[8]) / float(values[9])) * 100, 2),
                        'performance_state': values[10],
                        'clock_speed': float(values[11]),
                        'status': self._get_status(float(values[2]), 70, 90)
                    }
                    gpus.append(gpu_data)

            return {'available': True, 'count': len(gpus), 'gpus': gpus}

        except Exception as e:
            logger.error(f"GPU metrics error: {e}")
            return {'available': False, 'error': str(e)}

    def get_disk_metrics(self) -> Dict[str, Any]:
        """Get disk usage metrics"""
        try:
            partitions = []

            for part in psutil.disk_partitions():
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    partitions.append({
                        'device': part.device,
                        'mountpoint': part.mountpoint,
                        'fstype': part.fstype,
                        'total_gb': round(usage.total / (1024**3), 2),
                        'used_gb': round(usage.used / (1024**3), 2),
                        'free_gb': round(usage.free / (1024**3), 2),
                        'percent': round(usage.percent, 2),
                        'status': self._get_status(usage.percent, 80, 95)
                    })
                except PermissionError:
                    continue

            disk_io = psutil.disk_io_counters()

            return {
                'partitions': partitions,
                'io': {
                    'read_mb': round(disk_io.read_bytes / (1024**2), 2),
                    'write_mb': round(disk_io.write_bytes / (1024**2), 2),
                    'read_count': disk_io.read_count,
                    'write_count': disk_io.write_count
                }
            }
        except Exception as e:
            logger.error(f"Disk metrics error: {e}")
            return {'error': str(e)}

    def get_network_metrics(self) -> Dict[str, Any]:
        """Get network I/O metrics"""
        try:
            net_io = psutil.net_io_counters()

            if self.last_network_io:
                time_diff = time.time() - self.last_network_io['timestamp']
                if time_diff > 0:
                    bytes_sent_rate = (net_io.bytes_sent - self.last_network_io['bytes_sent']) / time_diff
                    bytes_recv_rate = (net_io.bytes_recv - self.last_network_io['bytes_recv']) / time_diff
                else:
                    bytes_sent_rate = 0
                    bytes_recv_rate = 0
            else:
                bytes_sent_rate = 0
                bytes_recv_rate = 0

            self.last_network_io = {
                'bytes_sent': net_io.bytes_sent,
                'bytes_recv': net_io.bytes_recv,
                'timestamp': time.time()
            }

            return {
                'bytes_sent_gb': round(net_io.bytes_sent / (1024**3), 2),
                'bytes_recv_gb': round(net_io.bytes_recv / (1024**3), 2),
                'packets_sent': net_io.packets_sent,
                'packets_recv': net_io.packets_recv,
                'errin': net_io.errin,
                'errout': net_io.errout,
                'dropin': net_io.dropin,
                'dropout': net_io.dropout,
                'send_rate_mbps': round(bytes_sent_rate / (1024**2), 2),
                'recv_rate_mbps': round(bytes_recv_rate / (1024**2), 2)
            }
        except Exception as e:
            logger.error(f"Network metrics error: {e}")
            return {'error': str(e)}

    def get_vllm_process_metrics(self) -> Dict[str, Any]:
        """Get vLLM process metrics"""
        try:
            vllm_processes = []

            for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'cpu_percent', 'memory_percent', 'memory_info']):
                try:
                    cmdline = proc.info.get('cmdline', [])
                    if cmdline and any('vllm' in str(arg).lower() for arg in cmdline):
                        vllm_processes.append({
                            'pid': proc.info['pid'],
                            'name': proc.info['name'],
                            'cpu_percent': round(proc.info['cpu_percent'], 2),
                            'memory_percent': round(proc.info['memory_percent'], 2),
                            'memory_mb': round(proc.info['memory_info'].rss / (1024**2), 2),
                            'status': proc.status()
                        })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            return {
                'found': len(vllm_processes) > 0,
                'count': len(vllm_processes),
                'processes': vllm_processes
            }
        except Exception as e:
            logger.error(f"vLLM process metrics error: {e}")
            return {'error': str(e)}

    def get_mysql_process_metrics(self) -> Dict[str, Any]:
        """Get MySQL process metrics"""
        try:
            mysql_processes = []

            for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'cpu_percent', 'memory_percent', 'memory_info']):
                try:
                    name = proc.info.get('name', '').lower()
                    if 'mysql' in name or 'mysqld' in name:
                        try:
                            connections = len(proc.net_connections())
                        except (psutil.AccessDenied, AttributeError):
                            connections = 0

                        mysql_processes.append({
                            'pid': proc.info['pid'],
                            'name': proc.info['name'],
                            'cpu_percent': round(proc.info['cpu_percent'], 2),
                            'memory_percent': round(proc.info['memory_percent'], 2),
                            'memory_mb': round(proc.info['memory_info'].rss / (1024**2), 2),
                            'connections': connections,
                            'status': proc.status()
                        })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            return {
                'found': len(mysql_processes) > 0,
                'count': len(mysql_processes),
                'processes': mysql_processes
            }
        except Exception as e:
            logger.error(f"MySQL process metrics error: {e}")
            return {'error': str(e)}

    def _get_status(self, value: float, warning_threshold: float, critical_threshold: float) -> str:
        """Get status based on thresholds"""
        if value >= critical_threshold:
            return 'critical'
        elif value >= warning_threshold:
            return 'warning'
        else:
            return 'ok'

    def run_speed_test(self) -> Dict[str, Any]:
        """
        Run a real internet speed test (download/upload/ping) using speedtest-cli.
        This is BLOCKING and takes ~10-20 seconds - callers must run it in a
        thread (e.g. via asyncio.to_thread) rather than the 2s metrics loop.
        Requires: pip install speedtest-cli
        """
        if not self.speedtest_lock.acquire(blocking=False):
            return {'error': 'A speed test is already running'}

        try:
            self.speedtest_running = True
            import speedtest

            st = speedtest.Speedtest()
            st.get_best_server()

            download_bps = st.download()
            upload_bps = st.upload()
            ping_ms = st.results.ping
            server = st.results.server or {}

            result = {
                'download_mbps': round(download_bps / 1_000_000, 2),
                'upload_mbps': round(upload_bps / 1_000_000, 2),
                'ping_ms': round(ping_ms, 2),
                'server_name': server.get('sponsor', 'Unknown'),
                'server_location': f"{server.get('name', '')}, {server.get('country', '')}".strip(', '),
                'timestamp': datetime.now().isoformat()
            }

            self.db.insert_speedtest(result)
            logger.info(
                f"Speed test complete: {result['download_mbps']} Mbps down / "
                f"{result['upload_mbps']} Mbps up / {result['ping_ms']} ms ping"
            )
            return result

        except ImportError:
            error_msg = "speedtest-cli is not installed. Run: pip install speedtest-cli"
            logger.error(error_msg)
            return {'error': error_msg}
        except Exception as e:
            logger.error(f"Speed test error: {e}")
            return {'error': str(e)}
        finally:
            self.speedtest_running = False
            self.speedtest_lock.release()

    def get_all_metrics(self) -> Dict[str, Any]:
        """Get all system metrics and store in database"""
        metrics = {
            'timestamp': datetime.now().isoformat(),
            'cpu': self.get_cpu_metrics(),
            'memory': self.get_memory_metrics(),
            'gpu': self.get_gpu_metrics(),
            'disk': self.get_disk_metrics(),
            'network': self.get_network_metrics(),
            'vllm': self.get_vllm_process_metrics(),
            'mysql': self.get_mysql_process_metrics()
        }

        # Store in database
        self.db.insert_metrics(metrics)

        # Check for alerts
        self._check_alerts(metrics)

        return metrics

    def _check_alerts(self, metrics: Dict[str, Any]):
        """Check for alert conditions and store in database"""
        # CPU alerts
        if metrics['cpu'].get('status') == 'critical':
            self.db.insert_alert(
                'critical', 'CPU',
                f"CPU usage critical: {metrics['cpu'].get('percent')}%"
            )

        # Memory alerts
        if metrics['memory'].get('status') == 'critical':
            self.db.insert_alert(
                'critical', 'Memory',
                f"Memory usage critical: {metrics['memory'].get('percent')}%"
            )

        # GPU alerts
        if metrics['gpu'].get('available') and metrics['gpu'].get('gpus'):
            for gpu in metrics['gpu']['gpus']:
                if gpu.get('status') == 'critical':
                    self.db.insert_alert(
                        'critical', f"GPU {gpu['index']}",
                        f"GPU utilization critical: {gpu.get('utilization')}%"
                    )

                if gpu.get('memory_percent', 0) > 95:
                    self.db.insert_alert(
                        'critical', f"GPU {gpu['index']} Memory",
                        f"GPU memory critical: {gpu.get('memory_percent')}%"
                    )

        # vLLM process alerts
        if not metrics['vllm'].get('found'):
            self.db.insert_alert(
                'warning', 'vLLM',
                'vLLM process not detected'
            )


# Initialize monitor
monitor = SystemMonitor()

# Active WebSocket connections
active_connections: List[WebSocket] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    # Startup
    logger.info("🚀 VM Monitor Service Starting (SQLite Mode)...")
    logger.info(f"   GPU Available: {monitor.gpu_available}")
    logger.info(f"   CPU Cores: {psutil.cpu_count()}")
    logger.info(f"   Total RAM: {round(psutil.virtual_memory().total / (1024**3), 2)} GB")

    db_stats = monitor.db.get_database_stats()
    logger.info(f"   Database: {db_stats.get('metrics_count', 0)} records, {db_stats.get('database_size_mb', 0)} MB")

    yield

    # Shutdown
    logger.info("🛑 VM Monitor Service Shutting Down...")
    monitor.db.close()


# Initialize FastAPI app
app = FastAPI(title="VM Resource Monitor - SQLite", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/")
async def root():
    """Serve the dashboard HTML"""
    html_path = Path(__file__).parent / 'monitor_dashboard.html'

    if not html_path.exists():
        return HTMLResponse(
            content="<h1>Error: monitor_dashboard.html not found</h1>",
            status_code=404
        )

    with open(html_path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.get("/api/metrics")
async def get_metrics():
    """Get current metrics"""
    return JSONResponse(content=monitor.get_all_metrics())


@app.get("/api/history/recent")
async def get_recent_history(minutes: int = 5):
    """Get metrics from last N minutes (full resolution)"""
    data = monitor.db.get_recent_metrics(minutes)
    return JSONResponse(content={'data': data, 'count': len(data)})


@app.get("/api/history/range")
async def get_history_range(hours: int = 24):
    """Get metrics for time range (full resolution, up to 7 days)"""
    if hours > 168:  # 7 days
        hours = 168

    data = monitor.db.get_metrics_range(hours)
    return JSONResponse(content={'data': data, 'count': len(data), 'hours': hours})


@app.get("/api/history/summary")
async def get_history_summary(hours: int = 24):
    """Get statistical summary for time range"""
    if hours > 168:
        hours = 168

    summary = monitor.db.get_metrics_summary(hours)
    return JSONResponse(content=summary)


@app.get("/api/alerts")
async def get_alerts(limit: int = 20):
    """Get recent alerts"""
    alerts = monitor.db.get_recent_alerts(limit)
    return JSONResponse(content=alerts)


@app.get("/api/stats")
async def get_database_stats():
    """Get database statistics"""
    stats = monitor.db.get_database_stats()
    return JSONResponse(content=stats)


@app.post("/api/cleanup")
async def trigger_cleanup():
    """Manually trigger cleanup of old data"""
    monitor.db.cleanup_old_data()
    stats = monitor.db.get_database_stats()
    return JSONResponse(content={'status': 'cleanup complete', 'stats': stats})


@app.post("/api/speedtest/run")
async def run_speedtest():
    """
    Trigger a real internet speed test (download/upload/ping).
    Runs the blocking speedtest-cli call in a worker thread so it doesn't
    block the event loop (and therefore doesn't stall the /ws metrics stream).
    Takes roughly 10-20 seconds to complete.
    """
    if monitor.speedtest_running:
        return JSONResponse(content={'error': 'A speed test is already running'}, status_code=409)

    result = await asyncio.to_thread(monitor.run_speed_test)
    if 'error' in result:
        return JSONResponse(content=result, status_code=500)
    return JSONResponse(content=result)


@app.get("/api/speedtest/latest")
async def get_latest_speedtest():
    """Get the most recent speed test result (cached, does not run a new test)"""
    result = monitor.db.get_latest_speedtest()
    return JSONResponse(content=result or {})


@app.get("/api/speedtest/history")
async def get_speedtest_history(limit: int = 50):
    """Get recent speed test history"""
    results = monitor.db.get_speedtest_history(limit)
    return JSONResponse(content={'data': results, 'count': len(results)})


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates"""
    await websocket.accept()
    active_connections.append(websocket)

    try:
        while True:
            metrics = monitor.get_all_metrics()
            await websocket.send_json(metrics)
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        active_connections.remove(websocket)


if __name__ == "__main__":
    port = int(os.environ.get("VM_MONITOR_PORT", "8790"))
    # Serve HTTPS with the same self-signed cert as server.py (see
    # server.py's cert.pem/key.pem setup) so the dashboard's Monitor
    # Report iframe — which reuses the page's own protocol — doesn't try
    # an HTTPS handshake against a plain HTTP server.
    _cert_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cert.pem")
    _key_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "key.pem")
    _ssl_kwargs = {}
    if os.path.exists(_cert_path) and os.path.exists(_key_path):
        _ssl_kwargs = {"ssl_certfile": _cert_path, "ssl_keyfile": _key_path}
        print(f"Starting VM Monitor on https://0.0.0.0:{port} (self-signed cert)")
    else:
        print(f"Starting VM Monitor on http://0.0.0.0:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port, **_ssl_kwargs)