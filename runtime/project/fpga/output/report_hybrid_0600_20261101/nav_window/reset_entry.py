"""Separate normal-system-reset proof gate; never calls reset/reboot itself."""
KERNEL_REVIEW='b19d494b302d144d83c9f2a7f56c7e4576747f7d5c7ceecffbb97875f5b744fc'
KIND='NORMAL_SYSTEM_SOFT_RESET_OBSERVED_FRESH_UBOOT_EXPLICIT_FULL_BIT'
def digest(value):return isinstance(value,str) and len(value)==64 and all(c in '0123456789abcdef' for c in value)
def validate(receipt,new_boot,script_sha,expected_prior=None):
 if receipt.get('reset_entry_kind')!=KIND or receipt.get('physical_POR_proven') is not False or receipt.get('physical_POR_and_serial_entry_confirmed') is not False:raise RuntimeError('Normal reset must be separate from physical POR evidence')
 if receipt.get('system_reset_kernel_review_sha256')!=KERNEL_REVIEW or receipt.get('standard_reboot_requested_once') is not True or receipt.get('fresh_uboot_identity_observed') is not True or receipt.get('verified_script_crc_and_iminfo') is not True or receipt.get('explicit_full_bit_loadb_succeeded') is not True or receipt.get('kernel_start_observed') is not True:raise RuntimeError('Observed normal reset/U-Boot/full-bit sequence incomplete')
 prior=receipt.get('prior_boot_id')
 if not isinstance(prior,str) or len(prior)!=36 or prior==new_boot or receipt.get('boot_id')!=new_boot or (expected_prior is not None and prior!=expected_prior):raise RuntimeError('Actual pre/post system-reset boot binding differs')
 if receipt.get('verified_script_sha256')!=script_sha:raise RuntimeError('Verified one-shot entry script differs')
 for key in ['normal_reset_request_receipt_sha256','serial_transcript_sha256']:
  if not digest(receipt.get(key)):raise RuntimeError('Actual reset/serial receipt pin missing')
 return dict(reset_entry_kind=KIND,physical_POR_proven=False,prior_boot_id=prior,boot_id=new_boot)

def validate_manual_restore(receipt,new_boot,script_sha):
 if receipt.get('reset_entry_kind')!='MANUAL_PHYSICAL_POR_FRESH_UBOOT_EXPLICIT_ORIGINAL_FULL_BIT' or receipt.get('physical_POR_proven') is not True or receipt.get('physical_POR_and_serial_entry_confirmed') is not True:raise RuntimeError('Separate actual manual-POR restore proof required')
 if receipt.get('standard_reboot_requested_once') is not False or receipt.get('boot_id')!=new_boot or receipt.get('fresh_uboot_identity_observed') is not True or receipt.get('verified_script_crc_and_iminfo') is not True or receipt.get('explicit_full_bit_loadb_succeeded') is not True or receipt.get('kernel_start_observed') is not True or receipt.get('verified_script_sha256')!=script_sha or not digest(receipt.get('serial_transcript_sha256')):raise RuntimeError('Manual explicit original-bit restore sequence incomplete')
 return dict(reset_entry_kind=receipt['reset_entry_kind'],physical_POR_proven=True,boot_id=new_boot)
