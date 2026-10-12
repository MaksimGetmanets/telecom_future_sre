// Быстрая проверка (smoke): 2 виртуальных пользователя, 30 секунд, создание и чтение заказов через gateway.
// Запуск: make load-smoke (скрипт выполняется внутри кластера, адрес по умолчанию http://gateway.demo.svc:8080).
import http from 'k6/http';
import { check, sleep } from 'k6';

const BASE = __ENV.BASE_URL || 'http://gateway.demo.svc:8080';
const JSON_HEADERS = { headers: { 'Content-Type': 'application/json' } };

export const options = {
  vus: 2,
  duration: '30s',
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<300'],
  },
};

export default function () {
  const created = http.post(`${BASE}/orders`, JSON.stringify({ item: 'book', quantity: 1 }), JSON_HEADERS);
  check(created, { 'создание: 201': (r) => r.status === 201 });

  const list = http.get(`${BASE}/orders`);
  check(list, { 'список: 200': (r) => r.status === 200 });

  sleep(0.5);
}
