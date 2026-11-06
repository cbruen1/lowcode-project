# Attendance Tracker – Specification

Specification for Claude Code to build the application. Prepared 28 Oct 2026; revised 5 Nov 2026 for multiple organisations, weekly recurring classes, one admin per organisation, a platform-owner screen, a student directory and daylight saving rules.

## 1. Overview

A multi-tenant web application that records attendance for classes run by schools and other organisations. Each organisation has one admin and any number of tutors. A tutor creates a class that repeats weekly at the same day and time, then records attendance for each session by picking students' names from a pre-filled list. Students have no accounts. Optionally, a tutor can show a QR code so students check themselves in on their phones. The platform owner, who runs the service, creates organisations from a separate screen. Every organisation's data is fully isolated from every other's.

## 2. Users and roles

- **Platform owner (login required, outside any organisation):** runs the service. Signs in to a separate screen to create organisations and each organisation's single admin, and to edit all organisation details. Cannot see students or attendance. There is no self-service sign-up.
- **Admin (login required):** exactly one per organisation. Adds and manages the organisation's tutors, and can do everything a tutor can across all of the organisation's classes.
- **Tutor (login required):** creates and runs their own classes, creates and imports students, sees all students registered in the organisation, and records attendance in their own classes. A tutor cannot add or manage tutors or the admin.
- **Student (no login, no role):** a record in the system only. A tutor records their attendance. If QR self check-in is enabled for a class, a student may submit the public check-in form, which needs no account.

Permissions within an organisation:

| Capability | Admin | Tutor |
| --- | --- | --- |
| Add, deactivate and reset passwords of tutors | Yes | No |
| Edit organisation details or replace the admin | No (platform owner only) | No |
| Create, edit, end and cancel sessions of classes | All classes | Own classes |
| Reassign a class to another tutor | Yes | No |
| See all students registered in the organisation | Yes | Yes |
| Create, import and edit students | Yes | Yes |
| Enrol students in classes | Any class | Own classes |
| Record and correct attendance | All classes | Own classes |
| View audit log | Whole organisation | Own classes |
| Delete a student's data (GDPR) | Any student in the organisation | Any student in the organisation |

## 3. Technology and hosting

- **Language/framework:** Python (suggest Flask or FastAPI with Jinja2 templates, or Django; Claude Code may choose, keeping it simple).
- **Database:** SQLite (single file). Make the DB path configurable via environment variable. Use migrations (e.g. Alembic or Django migrations).
- **Hosting:** simple PaaS (Render, Railway or Fly.io). Include a Dockerfile or Procfile, a persistent-volume note for the SQLite file, HTTPS, and a README with deployment steps.
- **Frontend:** server-rendered HTML with minimal JavaScript. Mobile-first and responsive throughout: tutors will mostly record attendance on a phone or tablet.
- Include automated tests for core logic and a seed script that creates two demo organisations, each with an admin, a tutor, a class and students, so tenant isolation can be demonstrated and tested.

## 4. Data model

- **Organisation:** id, name, time\_zone (default Europe/Dublin), privacy\_contact\_email, active, created\_at.
- **User** (admins and tutors): id, organisation\_id, name, email (lower-cased, unique across the platform), password\_hash, role (admin / tutor; at most one admin per organisation, enforced by a unique index on organisation\_id where role is admin), active, must\_change\_password, created\_by, created\_at.
- **Student:** id, organisation\_id, full\_name, email (optional, lower-cased, unique within the organisation when present), created\_by (user), created\_at. Students have no password and cannot log in.
- **Class:** id, organisation\_id, tutor\_id (owner: the creator until reassigned), name, description (optional), weekday, start\_time (local), duration\_minutes, first\_date, ended\_on (empty while the class continues), late\_after\_minutes, qr\_checkin\_enabled (default false), checkin\_opens\_before\_minutes, checkin\_closes\_after\_minutes, created\_at.
- **Enrolment:** class\_id, student\_id, unique on the pair.
- **Session** (one weekly occurrence of a class): id, class\_id, date, starts\_at (UTC), status (scheduled / cancelled), qr\_token (random, at least 128 bits), created\_at. Unique on (class\_id, date).
- **Attendance:** id, session\_id, student\_id (empty only for a QR check-in from an unrecognised email), submitted\_name and submitted\_email (QR check-ins only), status (present / late / absent), source (tutor / self), enrolled (boolean), recorded\_by\_user\_id (empty for self check-ins), recorded\_at. Unique on (session\_id, student\_id), and for QR check-ins on (session\_id, lower-cased email).
- **AuditLog:** id, organisation\_id, user\_id or platform\_owner\_id (both empty for self check-ins), action, class\_id, session\_id, attendance\_id, before/after details (JSON), timestamp.

**PlatformOwner** belongs to no organisation and is separate from User: id, name, email (lower-cased, unique), password\_hash, active, created\_at. The first one is created by CLI.

Every tenant-owned table carries organisation\_id (directly, or through its parent) and every query is scoped by it. The admin and every tutor can see all students registered in their organisation, since students belong to the organisation and are enrolled into classes. Importing a student whose email already exists in the organisation links to the existing record instead of creating a duplicate.

## 5. Classes and recurring sessions

- **Creating a class:** a tutor enters a name, optional description, weekday, start time, duration and first date. The class then repeats every week on that weekday and time until it is ended. There is no end date to enter.
- **Time zone and daylight saving:** a class is defined by a local weekday and local start time in the organisation's time zone. Each session's UTC start (starts\_at) is calculated from that local date and time using the IANA time zone database (Python `zoneinfo` with the `tzdata` package), never by adding 7 days to a UTC value.
  - A 19:00 class stays at 19:00 local time before and after the clocks change, so its UTC start moves by an hour. In Ireland the clocks go forward on the last Sunday of March and back on the last Sunday of October.
  - A local time that does not exist (clocks going forward, for example 01:30) moves forward by the length of the gap (01:30 becomes 02:30). A local time that occurs twice (clocks going back) uses the first occurrence.
  - Sessions are generated per local date, so a session is never duplicated or skipped across a change. Check-in windows and late cutoffs are calculated from starts\_at.
  - Changing an organisation's time zone affects only future sessions that have no attendance recorded.
  - No hard-coded UTC offsets or transition dates anywhere. The `tzdata` package is a pinned dependency that must be updated routinely, because governments change the rules.
  - Automated tests cover the transitions in 2026 to 2028 (29 Mar and 25 Oct 2026, 28 Mar and 31 Oct 2027, 26 Mar and 29 Oct 2028), including a Sunday class on the transition day itself and classes in the weeks either side.
- **Sessions:** each weekly occurrence is a Session. The app keeps session records created from the first date up to 12 weeks ahead, using a daily scheduled command and also topping up whenever a class page is opened.
- **Cancelling one session:** a tutor can cancel a single week, for example a holiday. It stays visible as cancelled and no attendance can be recorded for it.
- **Ending a class:** sets ended\_on. No further sessions are created; existing sessions and attendance are kept.
- **Changing the schedule:** a new weekday or time applies only to future sessions that have no attendance recorded. Past sessions are unchanged.
- **Ownership:** the creating tutor owns a class. Only an admin can reassign it, for example when a tutor leaves.
- Other patterns (one-off, fortnightly, several times a week) are not supported.

## 6. Features

### 6.1 Authentication and user management

- Email and password login with securely hashed passwords (argon2 or bcrypt), session cookies (HttpOnly, Secure, SameSite), CSRF protection, and login rate limiting. A user belongs to exactly one organisation.
- The platform owner creates an organisation and its admin from the platform screen (see 6.9); the admin gets a temporary password and must change it at first login. A CLI command creates the first platform owner account and can also create organisations.
- Each organisation has exactly one admin. Only the platform owner can create, edit, replace or deactivate the admin account. The admin cannot add, remove or demote an admin, and there is no way to create a second admin.
- The admin can add tutors by creating an account with a temporary password, deactivate or reactivate tutors, and reset their passwords. Tutors cannot see or use any of this.
- A deactivated tutor's classes stay in place until the admin reassigns them.
- Every user can change their own password.

### 6.2 Classes

- Tutors create, edit, end and cancel sessions of their own classes (see 5). A tutor's class list shows only their classes; an admin's shows all classes in the organisation, filterable by tutor.

### 6.3 Students and enrolment

- Tutors and admins create students (full name, optional email), edit them, and enrol or remove them from classes they own (the admin: any class). Every student registered in the organisation is visible to every tutor and the admin (see 6.8).
- **CSV upload** (columns: name, email) into a class, with validation, a preview, and a report of duplicates and of existing students that were linked rather than created.
- Students without an email are allowed. They can only be recorded by a tutor, never by QR check-in. Two students with the same name get a warning when created.

### 6.4 Recording attendance

- Attendance is recorded per session. The tutor opens a session and sees a pre-filled list of the class's enrolled students; for each one they tap present, late or absent. Phone-friendly, with a search box and a "mark all present" shortcut.
- A tutor can add a student who is not enrolled (picked from the organisation's students, or created on the spot), which also enrols them.
- Sessions that have no recorded status for a student show that student as not yet recorded, distinct from absent.
- A tutor can record or change attendance for any past session of their own class. Future sessions cannot be recorded, and cancelled sessions cannot be recorded at all.
- Changing or clearing a recorded status is allowed and is written to the audit log.

### 6.5 Optional QR self check-in

- Off by default. A tutor turns it on per class (qr\_checkin\_enabled), with the check-in window (default 15 minutes before to 30 minutes after start) and the late cutoff (default 10 minutes after start).
- A **full-screen display page** per session shows a large QR code of the session's check-in URL, the class name and the date and time, for a projector. The QR is generated server-side (for example with the `qrcode` library) as inline SVG or PNG. Each session has its own token, so a new QR code is used each week.
- The public page `/checkin/<session-token>` shows the class name, date and time, and a form with **Full name** and **Email address**, plus the organisation's privacy notice. It is mobile-first. Match emails case-insensitively and trim whitespace. Rate-limit the endpoint modestly.
- Outside the window, show a friendly "Check-in is not open" message (too early versus closed). Within the window, the status is late if checked in more than the late cutoff after the start time, otherwise present.
- If the email matches an enrolled student, record attendance for that student, source self. A repeat submission for the same session is blocked with a friendly message such as "You're already checked in."
- If the email matches no enrolled student, accept it, record it with enrolled = false, and flag it for the tutor to review (link it to a student, or delete it).
- Success screen: "You're checked in, welcome \<name>." Nothing else. Tutors can see QR check-ins appear on the live session view.

### 6.6 Reports and views

- **Session view:** enrolled students with their status and recorded time, a running count (present, late, absent, not yet recorded), auto-refreshing every few seconds so QR check-ins show up, plus a section for flagged non-enrolled QR check-ins.
- **Class attendance grid:** students down the side, sessions across the top (past and cancelled sessions marked), each cell showing present, late, absent or blank for not recorded.
- CSV export, per-student percentages and other reports are **not** required in this version.

### 6.7 Audit trail

- Every creation, change or deletion of an attendance record, class, session cancellation or user writes an AuditLog entry: who, what, when, and before and after values.
- Tutors see the log for their own classes. Admins see the whole organisation's log.

### 6.8 Student directory (tutor screen)

- A screen listing every student registered in the tutor's organisation, reachable from the main navigation for tutors and the admin. It never shows another organisation's students.
- Each student appears as a **tile** showing their full name, with their email in smaller text when they have one. Tiles sit in a responsive grid: one or two columns on a phone, more on a tablet, laptop or desktop.
- Tiles are real buttons at least 48 px high, so a tap on a touch device, a click with a mouse, and Enter or Space on a keyboard all work, with a visible focus outline.
- A search box filters the tiles by name or email as the tutor types. Tiles are sorted alphabetically by name and shown 60 at a time, with a "show more" control.
- Selecting a tile opens that student's detail panel (full screen on a phone): name, email, the classes they are enrolled in (by class name), and actions to edit, enrol in one of the tutor's own classes, remove from one of the tutor's own classes, and delete the student's data with confirmation.
- An "Add student" button on the same screen creates a student. CSV import stays on the class page.

### 6.9 Platform owner screens

- Platform owners sign in at a separate address (for example `/platform/login`) with their own accounts, sessions and cookies. Organisation users cannot open these screens and platform owners cannot open organisation screens. The same security rules apply (hashed passwords, CSRF protection, login rate limiting).
- **Organisation list:** every organisation with its name, time zone, active status, admin name and email, and counts of tutors, classes and students. Searchable.
- **Create organisation:** a form with organisation name, time zone (default Europe/Dublin, chosen from the IANA list), privacy contact email, and the admin's name and email. Saving creates the organisation and its single admin with a temporary password, shown once on screen. The app sends no email.
- **Edit organisation:** the platform owner can edit all organisation details: name, time zone, privacy contact email, and active or inactive (inactive blocks login for all of the organisation's users and closes QR check-in). They can also edit the admin's name and email, reset the admin's password, or replace the admin, which deactivates the old admin and creates a new one, so there is always exactly one active admin. Changing the time zone shows a warning that only future sessions without attendance move.
- Platform owner screens show organisation-level details and counts only, never student names, emails or attendance.
- Every platform owner action is written to the audit log with platform\_owner\_id. Deleting an organisation stays a CLI-only command.

## 7. Privacy and data protection (GDPR, Ireland)

- Collect only a student's full name and, optionally, email. For users, only name and email.
- Each organisation is the data controller for its students' data; the platform operator acts as processor. The QR check-in form shows a privacy notice built from the organisation's name and privacy contact email, stating purpose, retention approach and how to request deletion.
- The admin and any tutor can, for any student in their organisation, **manually delete** a student's data: the student record, enrolments and attendance records, including QR submissions matched by email. A confirmation step is required, and the audit log records the deletion without retaining the deleted personal data.
- The platform owner can delete an entire organisation and all its data with a CLI command.
- Automatic retention limits are out of scope for now.

## 8. Security and non-functional requirements

- **Tenant isolation:** every query is scoped by organisation\_id, and role and ownership checks run server-side on every route. Requests for another organisation's or another tutor's records return 404. Automated tests must cover cross-organisation and cross-tutor access, a tutor attempting any user-management action, and organisation users attempting platform owner routes (and the reverse).
- Session tokens and QR tokens are random and unguessable (at least 128 bits).
- All times are stored in UTC and displayed in the organisation's time zone; window checks and weekly recurrence follow the daylight saving rules in section 5, using the IANA time zone database.
- Server-side validation of all inputs, parameterised queries or ORM, output escaping, secure headers.
- Secrets and config (secret key, DB path, base URL) via environment variables.
- Accessible markup (labels, contrast, keyboard use), working on current mobile browsers.
- SQLite concurrency: enable WAL mode and handle the duplicate-check race with unique constraints. Run as a single instance, and note this in the README.

## 9. Out of scope (this version)

- Self-service organisation sign-up, billing, single sign-on, platform owner access to student data, more than one admin per organisation.
- Recurrence other than weekly, one-off sessions, several tutors on one class.
- Email notifications, rotating or expiring QR codes, location checks.
- CSV export, per-student reports, automatic data retention, per-organisation branding, student accounts.

## 10. Acceptance criteria

- The platform owner signs in on the platform screen, creates an organisation and its single admin, and can edit every organisation detail; the admin logs in and is forced to change the temporary password. Organisation users cannot open the platform screens.
- The admin can add and deactivate tutors. A second admin cannot be created for an organisation by any route, and only the platform owner can replace the admin. A tutor cannot add or manage users, and the user-management pages and routes are refused for tutors.
- A tutor creates a class and sees its sessions repeat weekly at the same local time, including across the March and October clock changes, shown by tests for 2026 to 2028.
- A tutor imports students by CSV, enrols them, and records present, late or absent from the pre-filled list on a phone.
- A cancelled session cannot have attendance recorded. An ended class creates no new sessions and keeps its history.
- A tutor sees only their own classes; the admin sees all classes in the organisation; nobody sees another organisation's data.
- A tutor sees every student registered in their organisation as tiles that respond to tap, click and keyboard on a phone, tablet and desktop, and can search them.
- With QR check-in enabled: a student can scan, submit name and email within the window and see a confirmation; repeats are blocked; late check-ins are marked late; an unrecognised email is accepted and flagged.
- The session view updates as students check in; the class grid shows present, late, absent and not recorded correctly.
- Changes to attendance are recorded in the audit log.
- An admin or tutor can delete a student's data, and the audit log keeps no personal data afterwards.
- The app runs with a SQLite database and deploys to a simple PaaS following the README.

## 11. Design

- **Source of truth for appearance:** the [Attendance Tracker design system](https://claude.ai/artifact/4SipUb6U8kjphtaXuqcPwv) (the Slate and mist palette, type, spacing, radii and four components) and the [screen mockups](https://claude.ai/artifact/GzzJMQv4CmzWcDbeFNmAXJ). Mockup names and numbers are examples only. Where they disagree with this spec, this spec wins on behaviour and the mockups win on appearance.
- **Look:** minimalist and muted. One primary button per screen, flat surfaces with hairline borders, no gradients, and shadows only on menus and dialogs. Status is always shown with a word and an icon as well as a colour.
- **Tokens:** define every colour, size, spacing step and radius from the design system as CSS variables in one stylesheet, and use them by name everywhere, with no raw hex values in templates. Changing the palette later must be a one-file edit.
- **Fully responsive, mobile-first:** every screen works on a phone (up to 599px wide), a tablet (600 to 1023px) and a laptop or desktop (1024px and up), with page content centred at a maximum of 1120px. Tutors mostly use a phone or tablet, so touch comes first.
- **Touch and accessibility:** anything tapped is at least 48px high and wide. Text contrast is at least 4.5:1 and control borders at least 3:1. Every interactive element has a visible 2px focus ring and works from the keyboard. Student tiles are real buttons.
- **Font:** Inter, falling back to the system font. Body text is 16px on every screen size.
- **Mockups exist for:** sign in, the tutor's class list, recording attendance, the student directory, the platform owner's organisation list, editing an organisation, and the QR display, each at laptop, tablet and phone width.
- **Screens without mockups** follow the same system:
  - **Student detail on a phone:** the detail panel from the student directory opens full screen from the tile, with a back button and the same actions as on larger screens (edit, enrol in a class, remove from a class, delete the student's data with confirmation).
  - **Tutors screen (admin only):** a list of tutors as rows with name, email and active status, an Add tutor form (name, email, temporary password shown once), and deactivate, reactivate and reset password actions. Stacked cards on a phone.
  - **Class attendance grid:** a table inside a card, with students down the side and sessions across the top, using the status chips. The student name column stays fixed and the table scrolls sideways inside its card on a phone.
  - **Audit log:** rows newest first showing who, what and when, with before and after details on selection. Stacked on a phone, a table on a laptop.

## 12. Build decisions

Decisions made while building the first version, where the spec left room. Code, tests and README are in the delivered project.

- **Single instance.** One gunicorn worker and one instance, because SQLite allows one writer and the login and check-in rate limits are held in memory. Scaling out needs Postgres and a shared limiter store.
- **Check-in rate limit.** 60 per minute per IP (login is 10 per minute), because a whole classroom shares one Wi-Fi address.
- **One session cookie** serves both school users and the platform owner. They are separate accounts with separate login pages (`/login`, `/platform/login`).
- **Sessions.** About 12 weeks are kept ahead, topped up by a daily command and when a class page is opened. History is backfilled only when a class is first created, so a weekday change never recreates past sessions.
- **Schedule changes** touch only future sessions with no attendance. Ending a class removes future empty sessions and keeps past ones.
- **Recording rule.** A session can be recorded from its local date onward (not before the day), and never when cancelled.
- **Replacing an admin** turns the old admin into an inactive tutor, so their classes stay and can be reassigned.
- **Passwords.** Argon2, minimum 10 characters. Temporary passwords are shown once on screen and no email is sent; the user must change it at first sign-in.
- **Audit log** stores ids and status words only, never names or emails, so deleting a student leaves nothing personal behind.
- **Privacy notice** on the check-in form is a placeholder, set through the `PRIVACY_NOTICE` setting. Replace it with approved legal text before go-live.
- **Security headers.** Strict content security policy with no inline scripts or styles.
- **Fonts.** Inter if installed, otherwise the system font, so there are no external font requests.
- **Organisation deletion** is command-line only and asks for the organisation name.
