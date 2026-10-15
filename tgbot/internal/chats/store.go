// Package chats: список чатов, в которые бот шлёт алерты.
// Чат подключается командой /start, поэтому chat id не нужно искать и вписывать руками.
// Список хранится в памяти и, если задан путь, в JSON-файле (переживает перезапуск процесса).
package chats

import (
	"encoding/json"
	"os"
	"path/filepath"
	"sort"
	"sync"
)

// Store потокобезопасен. Чаты из конфигурации (TELEGRAM_CHAT_ID) закреплены и командой /stop не удаляются.
type Store struct {
	mu   sync.RWMutex
	ids  map[int64]bool // true = закреплён конфигурацией
	path string
}

// Open читает файл (если он есть и путь задан) и добавляет закреплённые чаты.
// Повреждённый или отсутствующий файл не ошибка: список просто начнётся с закреплённых чатов.
func Open(path string, pinned ...int64) *Store {
	s := &Store{ids: map[int64]bool{}, path: path}
	if path != "" {
		if raw, err := os.ReadFile(path); err == nil {
			var saved []int64
			if json.Unmarshal(raw, &saved) == nil {
				for _, id := range saved {
					s.ids[id] = false
				}
			}
		}
	}
	for _, id := range pinned {
		if id != 0 {
			s.ids[id] = true
		}
	}
	return s
}

// Add подключает чат. added=false, если он уже был в списке. Ошибка записи файла не отменяет подключение.
func (s *Store) Add(id int64) (added bool, err error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.ids[id]; ok {
		return false, nil
	}
	s.ids[id] = false
	return true, s.saveLocked()
}

// Remove отключает чат. Закреплённый конфигурацией чат остаётся: ok=false.
func (s *Store) Remove(id int64) (ok bool, err error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	pinned, exists := s.ids[id]
	if !exists || pinned {
		return false, nil
	}
	delete(s.ids, id)
	return true, s.saveLocked()
}

func (s *Store) Has(id int64) bool {
	s.mu.RLock()
	defer s.mu.RUnlock()
	_, ok := s.ids[id]
	return ok
}

// All возвращает чаты в стабильном порядке.
func (s *Store) All() []int64 {
	s.mu.RLock()
	defer s.mu.RUnlock()
	out := make([]int64, 0, len(s.ids))
	for id := range s.ids {
		out = append(out, id)
	}
	sort.Slice(out, func(i, j int) bool { return out[i] < out[j] })
	return out
}

func (s *Store) saveLocked() error {
	if s.path == "" {
		return nil
	}
	var dynamic []int64
	for id, pinned := range s.ids {
		if !pinned {
			dynamic = append(dynamic, id)
		}
	}
	sort.Slice(dynamic, func(i, j int) bool { return dynamic[i] < dynamic[j] })
	raw, err := json.Marshal(dynamic)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(s.path), 0o755); err != nil {
		return err
	}
	return os.WriteFile(s.path, raw, 0o600)
}
