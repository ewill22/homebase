-- homebase MySQL schema (database: homebase)
-- Frozen snapshot of every table the homebase code depends on.
--
-- To apply to a fresh DB: mysql -u guapa_will -p homebase < schema.sql
-- To regenerate from current DB: see scripts/dump_schema.sh
--
-- Note: guapa.* tables (parcels, sr1a_sales, tax_list, strain_stock) live in
-- a separate database and are NOT in this file.

CREATE TABLE `bet_history` (
  `id` int NOT NULL AUTO_INCREMENT,
  `placed_at` datetime NOT NULL,
  `sport` varchar(10) DEFAULT 'NHL',
  `team_bet` varchar(80) NOT NULL,
  `matchup` varchar(160) NOT NULL,
  `odds` int NOT NULL,
  `stake` decimal(8,2) NOT NULL,
  `payout` decimal(8,2) DEFAULT NULL,
  `result` enum('WON','LOST','CASHED_OUT','PENDING') NOT NULL,
  `notes` varchar(255) DEFAULT NULL,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `placed_at` (`placed_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE `dispensary_menu` (
  `id` int NOT NULL AUTO_INCREMENT,
  `snapshot_id` varchar(36) NOT NULL,
  `captured_at` datetime NOT NULL,
  `dispensary` varchar(100) NOT NULL,
  `brand` varchar(150) DEFAULT NULL,
  `product_name` varchar(255) NOT NULL,
  `strain_name` varchar(150) DEFAULT NULL,
  `category` varchar(100) DEFAULT NULL,
  `strain_type` varchar(50) DEFAULT NULL,
  `price` decimal(8,2) DEFAULT NULL,
  `sale_price` decimal(8,2) DEFAULT NULL,
  `discount_pct` decimal(5,3) DEFAULT NULL,
  `discount_label` varchar(150) DEFAULT NULL,
  `in_stock` tinyint(1) NOT NULL DEFAULT '1',
  `package_id` varchar(100) DEFAULT NULL,
  `thc` decimal(5,2) DEFAULT NULL,
  `thca` decimal(5,2) DEFAULT NULL,
  `cbd` decimal(5,2) DEFAULT NULL,
  `cbda` decimal(5,2) DEFAULT NULL,
  `cbg` decimal(5,2) DEFAULT NULL,
  `cbn` decimal(5,2) DEFAULT NULL,
  `limonene` decimal(5,2) DEFAULT NULL,
  `beta_myrcene` decimal(5,2) DEFAULT NULL,
  `beta_caryophyllene` decimal(5,2) DEFAULT NULL,
  `humulene` decimal(5,2) DEFAULT NULL,
  `alpha_pinene` decimal(5,2) DEFAULT NULL,
  `beta_pinene` decimal(5,2) DEFAULT NULL,
  `linalool` decimal(5,2) DEFAULT NULL,
  `ocimene` decimal(5,2) DEFAULT NULL,
  `terpinolene` decimal(5,2) DEFAULT NULL,
  `bisabolol` decimal(5,2) DEFAULT NULL,
  `menu_url` text,
  PRIMARY KEY (`id`),
  KEY `idx_snapshot` (`snapshot_id`),
  KEY `idx_disp_time` (`dispensary`,`captured_at`),
  KEY `idx_strain` (`strain_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE `homebase_log` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `user_id` int NOT NULL DEFAULT '1',
  `event_type` varchar(50) NOT NULL,
  `status` varchar(20) NOT NULL DEFAULT 'ok',
  `message` text,
  `detail` text,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_user_event` (`user_id`,`event_type`),
  KEY `idx_created` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE `hrb_daily_pnl` (
  `date` date NOT NULL,
  `start_balance` decimal(10,2) DEFAULT NULL,
  `end_balance` decimal(10,2) DEFAULT NULL,
  `net` decimal(10,2) GENERATED ALWAYS AS ((`end_balance` - `start_balance`)) STORED,
  `note` varchar(200) DEFAULT NULL,
  `recorded_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE `odds_api_usage` (
  `month_key` varchar(7) NOT NULL,
  `paid_calls` int NOT NULL DEFAULT '0',
  `last_call_at` datetime DEFAULT NULL,
  `last_endpoint` varchar(40) DEFAULT NULL,
  `updated_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`month_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE `odds_flip_history` (
  `id` int NOT NULL AUTO_INCREMENT,
  `event_id` varchar(64) NOT NULL,
  `detected_at` datetime NOT NULL,
  `favorite_side` enum('home','away') NOT NULL,
  `favorite_team` varchar(120) DEFAULT NULL,
  `opening_ml` int NOT NULL,
  `current_ml` int NOT NULL,
  `home_score` int DEFAULT NULL,
  `away_score` int DEFAULT NULL,
  `period` tinyint DEFAULT NULL,
  `message` text,
  `sms_sent` tinyint(1) DEFAULT '0',
  PRIMARY KEY (`id`),
  KEY `idx_event` (`event_id`),
  KEY `idx_detected` (`detected_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE `odds_games` (
  `event_id` varchar(64) NOT NULL,
  `home` varchar(120) NOT NULL,
  `away` varchar(120) NOT NULL,
  `commence_time` datetime NOT NULL,
  `opening_ml_home` int DEFAULT NULL,
  `opening_ml_away` int DEFAULT NULL,
  `opening_favorite` enum('home','away') DEFAULT NULL,
  `opening_captured_at` datetime DEFAULT NULL,
  `current_ml_home` int DEFAULT NULL,
  `current_ml_away` int DEFAULT NULL,
  `last_polled_at` datetime DEFAULT NULL,
  `period` tinyint DEFAULT NULL,
  `home_score` int DEFAULT NULL,
  `away_score` int DEFAULT NULL,
  `status` varchar(24) DEFAULT 'scheduled',
  `alerted` tinyint(1) DEFAULT '0',
  `alerted_at` datetime DEFAULT NULL,
  `final` tinyint(1) DEFAULT '0',
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  `nhl_game_id` bigint DEFAULT NULL,
  `last_cf_home` float DEFAULT NULL,
  `last_cf_away` float DEFAULT NULL,
  `last_cf_attempts` int DEFAULT NULL,
  `last_cf_alert_dir` enum('below','above') DEFAULT NULL,
  `last_cf_checked_at` datetime DEFAULT NULL,
  `brief_sent_at` datetime DEFAULT NULL,
  `flip_ml` int DEFAULT NULL,
  `lock_alerted_at` datetime DEFAULT NULL,
  PRIMARY KEY (`event_id`),
  KEY `idx_status` (`status`),
  KEY `idx_commence` (`commence_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE `odds_watch` (
  `id` int NOT NULL AUTO_INCREMENT,
  `event_id` varchar(64) NOT NULL,
  `team_abbrev` varchar(4) DEFAULT NULL,
  `requested_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  `active` tinyint(1) DEFAULT '1',
  `last_update_sent_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_event` (`event_id`),
  KEY `idx_active` (`active`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE `spotify_plays` (
  `id` int NOT NULL AUTO_INCREMENT,
  `played_at` datetime NOT NULL,
  `user_id` int NOT NULL DEFAULT '1',
  `track_id` varchar(50) NOT NULL,
  `track_name` varchar(500) NOT NULL,
  `duration_ms` int DEFAULT NULL,
  `explicit` tinyint(1) DEFAULT NULL,
  `popularity` tinyint DEFAULT NULL,
  `track_number` smallint DEFAULT NULL,
  `disc_number` smallint DEFAULT NULL,
  `track_uri` varchar(100) DEFAULT NULL,
  `artist_id` varchar(50) DEFAULT NULL,
  `artist_name` varchar(500) DEFAULT NULL,
  `extra_artists` varchar(1000) DEFAULT NULL,
  `album_id` varchar(50) DEFAULT NULL,
  `album_name` varchar(500) DEFAULT NULL,
  `album_type` varchar(20) DEFAULT NULL,
  `album_release` varchar(20) DEFAULT NULL,
  `album_tracks` smallint DEFAULT NULL,
  `album_uri` varchar(100) DEFAULT NULL,
  `context_type` varchar(50) DEFAULT NULL,
  `context_uri` varchar(200) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_play` (`played_at`,`track_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE `user_calendars` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int NOT NULL,
  `calendar_id` varchar(255) NOT NULL,
  `label` varchar(100) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_user` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE `user_cities` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int NOT NULL,
  `display_order` tinyint NOT NULL DEFAULT '0',
  `name` varchar(100) NOT NULL,
  `lat` decimal(9,4) NOT NULL,
  `lon` decimal(9,4) NOT NULL,
  `temp_unit` varchar(12) NOT NULL DEFAULT 'fahrenheit',
  `wind_unit` varchar(8) NOT NULL DEFAULT 'mph',
  PRIMARY KEY (`id`),
  KEY `idx_user` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE `users` (
  `user_id` int NOT NULL AUTO_INCREMENT,
  `display_name` varchar(100) NOT NULL,
  `send_to_email` varchar(255) NOT NULL,
  `timezone` varchar(64) NOT NULL DEFAULT 'America/New_York',
  `birthday` date DEFAULT NULL,
  `trusted_senders` text,
  `logo_url` varchar(500) DEFAULT NULL,
  `active` tinyint(1) NOT NULL DEFAULT '1',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE `weather` (
  `id` int NOT NULL AUTO_INCREMENT,
  `recorded_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `temp_f` decimal(4,1) DEFAULT NULL,
  `humidity_pct` int DEFAULT NULL,
  `wind_mph` decimal(4,1) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
