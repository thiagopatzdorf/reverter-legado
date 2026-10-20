-- Semente do caso RealWorld (gerada por casos/realworld.py semente; não edite à mão).
-- Senhas com sal fixo: a semente sai igual a cada geração.
INSERT INTO users (id, username, email, password, bio, image, created_at, updated_at) VALUES (1, 'alice', 'alice@exemplo.io', '$2y$10$abcdefghijklmnopqrstuunlrCzdFzGVsj53hQcA90jAGUrvylgBK', 'Escreve sobre PHP.', NULL, '2026-10-01 10:00:00', '2026-10-01 10:00:00');
INSERT INTO users (id, username, email, password, bio, image, created_at, updated_at) VALUES (2, 'bruno', 'bruno@exemplo.io', '$2y$10$bcdefghijklmnopqrstuvuqpp7I/vO2MbGaJSOqGIg1d/f04K766W', NULL, 'https://exemplo.io/bruno.png', '2026-10-01 10:01:00', '2026-10-01 10:01:00');
INSERT INTO users (id, username, email, password, bio, image, created_at, updated_at) VALUES (3, 'carla', 'carla@exemplo.io', '$2y$10$cdefghijklmnopqrstuvwuqvnCtvI.kT91np4fg.grKoMeHZGWYMe', 'Python e dados.', NULL, '2026-10-01 10:02:00', '2026-10-01 10:02:00');
INSERT INTO articles (id, author_id, slug, title, description, body, created_at, updated_at) VALUES (1, 1, 'como-migrar-php', 'Como migrar PHP', 'Um roteiro curto', 'Corpo do artigo um.', '2026-10-02 09:00:00', '2026-10-02 09:00:00');
INSERT INTO articles (id, author_id, slug, title, description, body, created_at, updated_at) VALUES (2, 2, 'laravel-na-pratica', 'Laravel na prática', 'Exemplos reais', 'Corpo do artigo dois.', '2026-10-03 09:00:00', '2026-10-03 09:00:00');
INSERT INTO articles (id, author_id, slug, title, description, body, created_at, updated_at) VALUES (3, 1, 'contratos-de-api', 'Contratos de API', 'O que o legado promete', 'Corpo do artigo três.', '2026-10-04 09:00:00', '2026-10-04 09:00:00');
INSERT INTO articles (id, author_id, slug, title, description, body, created_at, updated_at) VALUES (4, 3, 'fastapi-do-zero', 'FastAPI do zero', 'Pydantic e rotas', 'Corpo do artigo quatro.', '2026-10-05 09:00:00', '2026-10-05 09:00:00');
INSERT INTO tags (id, name, created_at, updated_at) VALUES (1, 'php', '2026-10-02 09:00:00', '2026-10-02 09:00:00');
INSERT INTO tags (id, name, created_at, updated_at) VALUES (2, 'laravel', '2026-10-03 09:00:00', '2026-10-03 09:00:00');
INSERT INTO tags (id, name, created_at, updated_at) VALUES (3, 'python', '2026-10-05 09:00:00', '2026-10-05 09:00:00');
INSERT INTO article_tag (article_id, tag_id) VALUES (1, 1);
INSERT INTO article_tag (article_id, tag_id) VALUES (2, 1);
INSERT INTO article_tag (article_id, tag_id) VALUES (2, 2);
INSERT INTO article_tag (article_id, tag_id) VALUES (3, 1);
INSERT INTO article_tag (article_id, tag_id) VALUES (4, 3);
INSERT INTO comments (id, article_id, author_id, body, created_at, updated_at) VALUES (1, 1, 2, 'Muito bom.', '2026-10-06 08:00:00', '2026-10-06 08:00:00');
INSERT INTO comments (id, article_id, author_id, body, created_at, updated_at) VALUES (2, 1, 3, 'Ajudou aqui.', '2026-10-06 08:05:00', '2026-10-06 08:05:00');
INSERT INTO comments (id, article_id, author_id, body, created_at, updated_at) VALUES (3, 2, 1, 'Faltou testes.', '2026-10-06 08:10:00', '2026-10-06 08:10:00');
INSERT INTO article_favorite (article_id, user_id) VALUES (1, 2);
INSERT INTO article_favorite (article_id, user_id) VALUES (2, 1);
INSERT INTO article_favorite (article_id, user_id) VALUES (4, 1);
INSERT INTO author_follower (author_id, follower_id) VALUES (1, 2);
INSERT INTO author_follower (author_id, follower_id) VALUES (3, 1);
