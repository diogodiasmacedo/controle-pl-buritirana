-- Execute este script no Supabase SQL Editor
-- (Dashboard → SQL Editor → New query → cole e execute)

-- Tabela de registros de PLs
create table if not exists registros (
  id            uuid primary key default gen_random_uuid(),
  numero        text,
  tipo          text,
  data          text,
  autoria       text,
  ementa        text,
  resultado     text default 'Pendente',
  data_votacao  text,
  lei           text,
  observacoes   text,
  created_at    timestamptz default now()
);

-- Tabela de documentos anexados
create table if not exists documentos (
  id            uuid primary key default gen_random_uuid(),
  registro_id   uuid references registros(id) on delete cascade,
  nome          text,
  descricao     text,
  storage_path  text,
  url           text,
  tamanho       bigint,
  tipo          text,
  created_at    timestamptz default now()
);

-- Habilitar acesso público (Row Level Security desativado para uso interno)
alter table registros enable row level security;
alter table documentos enable row level security;

create policy "acesso total registros" on registros for all using (true) with check (true);
create policy "acesso total documentos" on documentos for all using (true) with check (true);
