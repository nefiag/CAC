SELECT 'account_sets', count(*) FROM tenants_account_sets;
SELECT 'admin_users', count(*) FROM auth_users WHERE role = 'ADMIN' AND is_active;
SELECT 'unbalanced_vouchers', count(*) FROM (
  SELECT v.id FROM vouchers v JOIN voucher_entries e ON e.voucher_id = v.id
  GROUP BY v.id HAVING round(sum(e.debit_amount), 2) <> round(sum(e.credit_amount), 2)
) q;
SELECT 'voucher_date_range', min(voucher_date)::text || '..' || max(voucher_date)::text FROM vouchers;
SELECT 'batches_' || document_type, count(*)
FROM financial_import_batches GROUP BY document_type ORDER BY 1;
SELECT 'trial_balance_group', account_set_id || '|' || period || '|'
  || round(sum(opening_debit) - sum(opening_credit), 2) || '|'
  || round(sum(period_debit) - sum(period_credit), 2) || '|'
  || round(sum(closing_debit) - sum(closing_credit), 2)
FROM financial_balance_snapshots
WHERE length(account_code) = 4
GROUP BY account_set_id, period ORDER BY 2;
SELECT 'active_duplicate_keys', count(*) FROM (
  SELECT account_set_id, period, document_type FROM financial_import_batches
  WHERE is_active GROUP BY 1, 2, 3 HAVING count(*) > 1
) q;
