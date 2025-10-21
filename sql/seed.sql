

INSERT INTO Notifications (id, user_id, event_type, status, attempts, context, sent_at, created_at, updated_at) VALUES
('a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11', '123e4567-e89b-12d3-a456-426614174000', 'payment_success', 'SENT', 0, '{"property_title": "Modern Apartment", "location": "Addis Ababa", "amount": 1500}', NOW() - INTERVAL '1 day', NOW() - INTERVAL '1 day', NOW() - INTERVAL '1 day'),
('a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a12', '123e4567-e89b-12d3-a456-426614174001', 'listing_approved', 'PENDING', 0, '{"property_title": "Spacious Villa", "location": "Bole, Addis Ababa"}', NOW(), NOW(), NOW()),
('a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a13', '123e4567-e89b-12d3-a456-426614174002', 'payment_failed', 'FAILED', 1, '{"property_title": "Studio Flat", "location": "Mexico, Addis Ababa", "amount": 800}', NOW() - INTERVAL '2 hours', NOW() - INTERVAL '1 day', NOW() - INTERVAL '2 hours'),
('a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a14', '123e4567-e89b-12d3-a456-426614174000', 'tenant_update', 'SENT', 0, '{"property_title": "Modern Apartment", "tenant_name": "John Doe"}', NOW() - INTERVAL '3 hours', NOW() - INTERVAL '1 day', NOW() - INTERVAL '3 hours'),
('a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a15', '123e4567-e89b-12d3-a456-426614174003', 'listing_approved', 'SENT', 0, '{"property_title": "Commercial Space", "location": "Piassa, Addis Ababa"}', NOW() - INTERVAL '1 day', NOW() - INTERVAL '1 day', NOW() - INTERVAL '1 day'),
('a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a16', '123e4567-e89b-12d3-a456-426614174001', 'payment_success', 'SENT', 0, '{"property_title": "Spacious Villa", "location": "Bole, Addis Ababa", "amount": 3000}', NOW() - INTERVAL '2 days', NOW() - INTERVAL '2 days', NOW() - INTERVAL '2 days'),
('a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a17', '123e4567-e89b-12d3-a456-426614174004', 'payment_failed', 'FAILED', 2, '{"property_title": "Guest House", "location": "Kazanchis, Addis Ababa", "amount": 1200}', NOW() - INTERVAL '1 hour', NOW() - INTERVAL '1 day', NOW() - INTERVAL '1 hour'),
('a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a18', '123e4567-e89b-12d3-a456-426614174000', 'listing_approved', 'PENDING', 0, '{"property_title": "New Listing", "location": "Gerji, Addis Ababa"}', NOW(), NOW(), NOW()),
('a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a19', '123e4567-e89b-12d3-a456-426614174005', 'tenant_update', 'SENT', 0, '{"property_title": "Family Home", "tenant_name": "Jane Smith"}', NOW() - INTERVAL '4 hours', NOW() - INTERVAL '1 day', NOW() - INTERVAL '4 hours'),
('a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a20', '123e4567-e89b-12d3-a456-426614174002', 'payment_success', 'SENT', 0, '{"property_title": "Studio Flat", "location": "Mexico, Addis Ababa", "amount": 800}', NOW() - INTERVAL '1 day', NOW() - INTERVAL '1 day', NOW() - INTERVAL '1 day');

-- Simulate 100+ notifications for scalability demo
DO $$
DECLARE
    i INT := 0;
    user_ids UUID[] := ARRAY[
        '123e4567-e89b-12d3-a456-426614174000',
        '123e4567-e89b-12d3-a456-426614174001',
        '123e4567-e89b-12d3-a456-426614174002',
        '123e4567-e89b-12d3-a456-426614174003',
        '123e4567-e89b-12d3-a456-426614174004',
        '123e4567-e89b-12d3-a456-426614174005'
    ];
    event_types TEXT[] := ARRAY['payment_success', 'listing_approved', 'payment_failed', 'tenant_update'];
    statuses TEXT[] := ARRAY['PENDING', 'SENT', 'FAILED'];
    property_titles TEXT[] := ARRAY['Cozy Studio', 'Luxury Penthouse', 'Family House', 'Commercial Office', 'Shared Room'];
    locations TEXT[] := ARRAY['Bole', 'Kazanchis', 'Mexico', 'Piassa', 'Gerji'];
BEGIN
    FOR i IN 11..120 LOOP
        INSERT INTO Notifications (id, user_id, event_type, status, attempts, context, sent_at, created_at, updated_at) VALUES
        (gen_random_uuid(),
         user_ids[1 + (i % array_length(user_ids, 1))],
         event_types[1 + (i % array_length(event_types, 1))],
         statuses[1 + (i % array_length(statuses, 1))],
         (i % 3), -- attempts
         jsonb_build_object(
             'property_title', property_titles[1 + (i % array_length(property_titles, 1))],
             'location', locations[1 + (i % array_length(locations, 1))],
             'amount', (i * 100) % 5000 + 500
         ),
         NOW() - (i * INTERVAL '10 minutes'),
         NOW() - (i * INTERVAL '10 minutes'),
         NOW() - (i * INTERVAL '10 minutes')
        );
    END LOOP;
END $$;
