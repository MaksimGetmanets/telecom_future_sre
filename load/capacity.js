// Тест вместимости: открытая модель (ramping-arrival-rate), нагрузка растёт ступенями по 1 минуте.
// Скорость запросов задана в запросах/с, а не числом пользователей: так видно, на какой нагрузке gateway перестаёт
// укладываться в SLO (p95 < 300 мс). Смесь: 80% чтение списка, 20% создание заказа.
// Запуск: make load-capacity (≈9 минут; на первом прогоне до 200 запросов/с p95 был 5 мс, поэтому уровни подняты), графики: Grafana, дашборд "k6: тест вместимости".
import http from 'k6/http';
import { check } from 'k6';

const BASE = __ENV.BASE_URL || 'http://gateway.demo.svc:8080';
const JSON_HEADERS = { headers: { 'Content-Type': 'application/json' } };
const LEVELS = [50, 100, 200, 300, 400, 600, 800, 1000, 1300]; // запросов в секунду

const stages = [];
for (const rate of LEVELS) {
  stages.push({ target: rate, duration: '15s' }); // разгон до ступени
  stages.push({ target: rate, duration: '45s' }); // удержание
}

export const options = {
  scenarios: {
    capacity: {
      executor: 'ramping-arrival-rate',
      startRate: 5,
      timeUnit: '1s',
      preAllocatedVUs: 100,
      maxVUs: 1000,
      stages,
    },
  },
  // Пороги не останавливают тест: нужна вся кривая. В итоговой сводке видно, какие нарушены.
  thresholds: {
    http_req_duration: ['p(95)<300'],
    http_req_failed: ['rate<0.01'],
  },
};

export default function () {
  if (Math.random() < 0.2) {
    const res = http.post(`${BASE}/orders`, JSON.stringify({ item: 'book', quantity: 1 }), JSON_HEADERS);
    check(res, { 'создание: 201': (r) => r.status === 201 });
  } else {
    const res = http.get(`${BASE}/orders`);
    check(res, { 'список: 200': (r) => r.status === 200 });
  }
}
