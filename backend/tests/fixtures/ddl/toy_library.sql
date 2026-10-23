CREATE SCHEMA IF NOT EXISTS "ds_toy_library";

CREATE TABLE "ds_toy_library"."authors" (
    "author_id" text NOT NULL,
    "full_name" text,
    "home_country" text,
    "birth_date" date,
    CONSTRAINT "pk_authors" PRIMARY KEY ("author_id")
);

CREATE TABLE "ds_toy_library"."books" (
    "isbn" text NOT NULL,
    "title" text,
    "author_id" text,
    "published" date,
    "page_count" integer,
    "price" numeric(8,2),
    "price_currency" text,
    "language" text,
    "shelf_code" text,
    "is_reference" boolean,
    CONSTRAINT "pk_books" PRIMARY KEY ("isbn")
);

CREATE TABLE "ds_toy_library"."loans" (
    "loan_id" text NOT NULL,
    "member_id" text,
    "isbn" text,
    "copy_number" text,
    "loaned_on" date NOT NULL,
    "due_on" date,
    "returned_at" timestamptz,
    "status" text,
    "late_fee" numeric(8,2),
    CONSTRAINT "pk_loans" PRIMARY KEY ("loan_id")
);

CREATE TABLE "ds_toy_library"."members" (
    "member_id" text NOT NULL,
    "full_name" text,
    "email" text,
    "joined_at" timestamptz,
    "tier" text,
    CONSTRAINT "pk_members" PRIMARY KEY ("member_id")
);

CREATE INDEX "ix_books__author_id" ON "ds_toy_library"."books" ("author_id");

CREATE INDEX "ix_loans__isbn" ON "ds_toy_library"."loans" ("isbn");

CREATE INDEX "ix_loans__member_id" ON "ds_toy_library"."loans" ("member_id");

