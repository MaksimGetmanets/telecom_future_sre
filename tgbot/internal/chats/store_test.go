package chats

import (
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

func TestAddRemoveAndPinned(t *testing.T) {
	s := Open("", 100)
	if !s.Has(100) {
		t.Fatal("закреплённый чат должен быть в списке")
	}
	if added, _ := s.Add(100); added {
		t.Error("повторное добавление не должно считаться новым")
	}
	if added, err := s.Add(-200); !added || err != nil {
		t.Fatalf("add: %v %v", added, err)
	}
	if ok, _ := s.Remove(100); ok {
		t.Error("закреплённый чат нельзя отключить командой")
	}
	if ok, _ := s.Remove(-200); !ok {
		t.Error("обычный чат должен отключаться")
	}
	if ok, _ := s.Remove(-200); ok {
		t.Error("повторное отключение ничего не делает")
	}
	if got := s.All(); !reflect.DeepEqual(got, []int64{100}) {
		t.Errorf("All = %v", got)
	}
}

func TestPersistenceAcrossRestart(t *testing.T) {
	path := filepath.Join(t.TempDir(), "sub", "chats.json")
	s := Open(path, 1)
	if _, err := s.Add(42); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Add(7); err != nil {
		t.Fatal(err)
	}
	s2 := Open(path, 1)
	if got := s2.All(); !reflect.DeepEqual(got, []int64{1, 7, 42}) {
		t.Fatalf("после перезапуска: %v", got)
	}
	// закреплённый чат в файл не пишется
	raw, _ := os.ReadFile(path)
	if string(raw) != "[7,42]" {
		t.Errorf("файл: %s", raw)
	}
}

func TestBrokenFileIsIgnored(t *testing.T) {
	path := filepath.Join(t.TempDir(), "chats.json")
	_ = os.WriteFile(path, []byte("не json"), 0o600)
	if got := Open(path, 5).All(); !reflect.DeepEqual(got, []int64{5}) {
		t.Errorf("All = %v", got)
	}
}

func TestWriteErrorKeepsChat(t *testing.T) {
	// путь внутри файла: MkdirAll не сможет создать каталог
	file := filepath.Join(t.TempDir(), "f")
	_ = os.WriteFile(file, nil, 0o600)
	s := Open(filepath.Join(file, "chats.json"))
	added, err := s.Add(9)
	if !added || err == nil {
		t.Fatalf("added=%v err=%v: чат должен подключиться, а ошибка записи быть возвращена", added, err)
	}
	if !s.Has(9) {
		t.Error("чат должен остаться в памяти")
	}
}
