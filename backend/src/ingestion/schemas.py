from pydantic import BaseModel, Field, field_validator, ConfigDict
from datetime import date, time, datetime
from typing import Optional, Union, Any
import json

class SAPTime(BaseModel):
    hours: int
    minutes: int
    seconds: int

    def to_time(self) -> time:
        return time(hour=self.hours, minute=self.minutes, second=self.seconds)

class BaseSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True, from_attributes=True)

    @field_validator("*", mode="before")
    @classmethod
    def transform_sap_data(cls, v: Any, info: Any) -> Any:
        if v == "":
            return None
        if isinstance(v, dict) and "hours" in v and "minutes" in v and "seconds" in v:
            return SAPTime(**v).to_time()
        if isinstance(v, str) and "T" in v and v.endswith("Z"):
            try:
                dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
                # Preserve full datetime for datetime-typed fields
                field_type = cls.model_fields.get(info.field_name)
                if field_type and field_type.annotation in (
                    Optional[datetime],
                    datetime,
                ):
                    return dt
                return dt.date()
            except ValueError:
                pass
        if isinstance(v, str) and v in ("True", "False"):
            return v == "True"
        return v

class BillingDocumentHeaderSchema(BaseSchema):
    billing_document: str = Field(alias="billingDocument")
    billing_document_type: Optional[str] = Field(None, alias="billingDocumentType")
    creation_date: Optional[date] = Field(None, alias="creationDate")
    creation_time: Optional[time] = Field(None, alias="creationTime")
    last_change_datetime: Optional[datetime] = Field(None, alias="lastChangeDateTime")
    billing_document_date: Optional[date] = Field(None, alias="billingDocumentDate")
    billing_document_is_cancelled: bool = Field(False, alias="billingDocumentIsCancelled")
    cancelled_billing_document: Optional[str] = Field(None, alias="cancelledBillingDocument")
    total_net_amount: Optional[float] = Field(None, alias="totalNetAmount")
    transaction_currency: Optional[str] = Field(None, alias="transactionCurrency")
    company_code: Optional[str] = Field(None, alias="companyCode")
    fiscal_year: Optional[str] = Field(None, alias="fiscalYear")
    accounting_document: Optional[str] = Field(None, alias="accountingDocument")
    sold_to_party: Optional[str] = Field(None, alias="soldToParty")

class BillingDocumentCancellationSchema(BaseSchema):
    billing_document: str = Field(alias="billingDocument")
    billing_document_type: Optional[str] = Field(None, alias="billingDocumentType")
    creation_date: Optional[date] = Field(None, alias="creationDate")
    creation_time: Optional[time] = Field(None, alias="creationTime")
    last_change_datetime: Optional[datetime] = Field(None, alias="lastChangeDateTime")
    billing_document_date: Optional[date] = Field(None, alias="billingDocumentDate")
    billing_document_is_cancelled: bool = Field(False, alias="billingDocumentIsCancelled")
    total_net_amount: Optional[float] = Field(None, alias="totalNetAmount")
    transaction_currency: Optional[str] = Field(None, alias="transactionCurrency")
    company_code: Optional[str] = Field(None, alias="companyCode")
    fiscal_year: Optional[str] = Field(None, alias="fiscalYear")
    accounting_document: Optional[str] = Field(None, alias="accountingDocument")
    sold_to_party: Optional[str] = Field(None, alias="soldToParty")

class BillingDocumentItemSchema(BaseSchema):
    billing_document: str = Field(alias="billingDocument")
    billing_document_item: str = Field(alias="billingDocumentItem")
    material: Optional[str] = Field(None, alias="material")
    billing_quantity: Optional[float] = Field(None, alias="billingQuantity")
    billing_quantity_unit: Optional[str] = Field(None, alias="billingQuantityUnit")
    net_amount: Optional[float] = Field(None, alias="netAmount")
    transaction_currency: Optional[str] = Field(None, alias="transactionCurrency")
    reference_sd_document: Optional[str] = Field(None, alias="referenceSdDocument")
    reference_sd_document_item: Optional[str] = Field(None, alias="referenceSdDocumentItem")

class BusinessPartnerAddressSchema(BaseSchema):
    business_partner: str = Field(alias="businessPartner")
    address_id: str = Field(alias="addressId")
    validity_start_date: Optional[date] = Field(None, alias="validityStartDate")
    validity_end_date: Optional[date] = Field(None, alias="validityEndDate")
    address_uuid: Optional[str] = Field(None, alias="addressUuid")
    address_time_zone: Optional[str] = Field(None, alias="addressTimeZone")
    city_name: Optional[str] = Field(None, alias="cityName")
    country: Optional[str] = Field(None, alias="country")
    po_box_is_without_number: bool = Field(False, alias="poBoxIsWithoutNumber")
    postal_code: Optional[str] = Field(None, alias="postalCode")
    region: Optional[str] = Field(None, alias="region")
    street_name: Optional[str] = Field(None, alias="streetName")

class BusinessPartnerSchema(BaseSchema):
    business_partner: str = Field(alias="businessPartner")
    customer: Optional[str] = Field(None, alias="customer")
    business_partner_category: Optional[str] = Field(None, alias="businessPartnerCategory")
    business_partner_full_name: Optional[str] = Field(None, alias="businessPartnerFullName")
    business_partner_grouping: Optional[str] = Field(None, alias="businessPartnerGrouping")
    business_partner_name: Optional[str] = Field(None, alias="businessPartnerName")
    created_by_user: Optional[str] = Field(None, alias="createdByUser")
    creation_date: Optional[date] = Field(None, alias="creationDate")
    creation_time: Optional[time] = Field(None, alias="creationTime")
    form_of_address: Optional[str] = Field(None, alias="formOfAddress")
    last_change_date: Optional[date] = Field(None, alias="lastChangeDate")
    organization_bp_name1: Optional[str] = Field(None, alias="organizationBpName1")
    organization_bp_name2: Optional[str] = Field(None, alias="organizationBpName2")
    business_partner_is_blocked: bool = Field(False, alias="businessPartnerIsBlocked")
    is_marked_for_archiving: bool = Field(False, alias="isMarkedForArchiving")

class CustomerCompanyAssignmentSchema(BaseSchema):
    customer: str = Field(alias="customer")
    company_code: str = Field(alias="companyCode")
    payment_terms: Optional[str] = Field(None, alias="paymentTerms")
    reconciliation_account: Optional[str] = Field(None, alias="reconciliationAccount")
    deletion_indicator: bool = Field(False, alias="deletionIndicator")
    customer_account_group: Optional[str] = Field(None, alias="customerAccountGroup")

class CustomerSalesAreaAssignmentSchema(BaseSchema):
    customer: str = Field(alias="customer")
    sales_organization: str = Field(alias="salesOrganization")
    distribution_channel: str = Field(alias="distributionChannel")
    division: str = Field(alias="division")
    complete_delivery_is_defined: bool = Field(False, alias="completeDeliveryIsDefined")
    currency: Optional[str] = Field(None, alias="currency")
    customer_payment_terms: Optional[str] = Field(None, alias="customerPaymentTerms")
    delivery_priority: Optional[str] = Field(None, alias="deliveryPriority")
    incoterms_classification: Optional[str] = Field(None, alias="incotermsClassification")
    incoterms_location1: Optional[str] = Field(None, alias="incotermsLocation1")
    shipping_condition: Optional[str] = Field(None, alias="shippingCondition")
    sls_unlmtd_ovrdeliv_is_allwd: bool = Field(False, alias="slsUnlmtdOvrdelivIsAllwd")
    exchange_rate_type: Optional[str] = Field(None, alias="exchangeRateType")

class JournalEntryItemAccountsReceivableSchema(BaseSchema):
    company_code: str = Field(alias="companyCode")
    fiscal_year: str = Field(alias="fiscalYear")
    accounting_document: str = Field(alias="accountingDocument")
    accounting_document_item: str = Field(alias="accountingDocumentItem")
    gl_account: Optional[str] = Field(None, alias="glAccount")
    reference_document: Optional[str] = Field(None, alias="referenceDocument")
    profit_center: Optional[str] = Field(None, alias="profitCenter")
    transaction_currency: Optional[str] = Field(None, alias="transactionCurrency")
    amount_in_transaction_currency: Optional[float] = Field(None, alias="amountInTransactionCurrency")
    company_code_currency: Optional[str] = Field(None, alias="companyCodeCurrency")
    amount_in_company_code_currency: Optional[float] = Field(None, alias="amountInCompanyCodeCurrency")
    posting_date: Optional[date] = Field(None, alias="postingDate")
    document_date: Optional[date] = Field(None, alias="documentDate")
    accounting_document_type: Optional[str] = Field(None, alias="accountingDocumentType")
    last_change_datetime: Optional[datetime] = Field(None, alias="lastChangeDateTime")
    customer: Optional[str] = Field(None, alias="customer")
    financial_account_type: Optional[str] = Field(None, alias="financialAccountType")
    clearing_date: Optional[date] = Field(None, alias="clearingDate")
    clearing_accounting_document: Optional[str] = Field(None, alias="clearingAccountingDocument")
    clearing_doc_fiscal_year: Optional[str] = Field(None, alias="clearingDocFiscalYear")

class OutboundDeliveryHeaderSchema(BaseSchema):
    delivery_document: str = Field(alias="deliveryDocument")
    actual_goods_movement_date: Optional[date] = Field(None, alias="actualGoodsMovementDate")
    actual_goods_movement_time: Optional[time] = Field(None, alias="actualGoodsMovementTime")
    creation_date: Optional[date] = Field(None, alias="creationDate")
    creation_time: Optional[time] = Field(None, alias="creationTime")
    hdr_general_incompletion_status: Optional[str] = Field(None, alias="hdrGeneralIncompletionStatus")
    last_change_date: Optional[date] = Field(None, alias="lastChangeDate")
    overall_goods_movement_status: Optional[str] = Field(None, alias="overallGoodsMovementStatus")
    overall_picking_status: Optional[str] = Field(None, alias="overallPickingStatus")
    shipping_point: Optional[str] = Field(None, alias="shippingPoint")

class OutboundDeliveryItemSchema(BaseSchema):
    delivery_document: str = Field(alias="deliveryDocument")
    delivery_document_item: str = Field(alias="deliveryDocumentItem")
    actual_delivery_quantity: Optional[float] = Field(None, alias="actualDeliveryQuantity")
    batch: Optional[str] = Field(None, alias="batch")
    delivery_quantity_unit: Optional[str] = Field(None, alias="deliveryQuantityUnit")
    plant: Optional[str] = Field(None, alias="plant")
    reference_sd_document: Optional[str] = Field(None, alias="referenceSdDocument")
    reference_sd_document_item: Optional[str] = Field(None, alias="referenceSdDocumentItem")
    storage_location: Optional[str] = Field(None, alias="storageLocation")

class PaymentAccountsReceivableSchema(BaseSchema):
    company_code: str = Field(alias="companyCode")
    fiscal_year: str = Field(alias="fiscalYear")
    accounting_document: str = Field(alias="accountingDocument")
    accounting_document_item: str = Field(alias="accountingDocumentItem")
    clearing_date: Optional[date] = Field(None, alias="clearingDate")
    clearing_accounting_document: Optional[str] = Field(None, alias="clearingAccountingDocument")
    clearing_doc_fiscal_year: Optional[str] = Field(None, alias="clearingDocFiscalYear")
    amount_in_transaction_currency: Optional[float] = Field(None, alias="amountInTransactionCurrency")
    transaction_currency: Optional[str] = Field(None, alias="transactionCurrency")
    amount_in_company_code_currency: Optional[float] = Field(None, alias="amountInCompanyCodeCurrency")
    company_code_currency: Optional[str] = Field(None, alias="companyCodeCurrency")
    customer: Optional[str] = Field(None, alias="customer")
    posting_date: Optional[date] = Field(None, alias="postingDate")
    document_date: Optional[date] = Field(None, alias="documentDate")
    gl_account: Optional[str] = Field(None, alias="glAccount")
    financial_account_type: Optional[str] = Field(None, alias="financialAccountType")
    profit_center: Optional[str] = Field(None, alias="profitCenter")

class PlantSchema(BaseSchema):
    plant: str = Field(alias="plant")
    plant_name: Optional[str] = Field(None, alias="plantName")
    valuation_area: Optional[str] = Field(None, alias="valuationArea")
    plant_customer: Optional[str] = Field(None, alias="plantCustomer")
    plant_supplier: Optional[str] = Field(None, alias="plantSupplier")
    factory_calendar: Optional[str] = Field(None, alias="factoryCalendar")
    sales_organization: Optional[str] = Field(None, alias="salesOrganization")
    address_id: Optional[str] = Field(None, alias="addressId")
    distribution_channel: Optional[str] = Field(None, alias="distributionChannel")
    division: Optional[str] = Field(None, alias="division")
    language: Optional[str] = Field(None, alias="language")
    is_marked_for_archiving: bool = Field(False, alias="isMarkedForArchiving")

class ProductDescriptionSchema(BaseSchema):
    product: str = Field(alias="product")
    language: str = Field(alias="language")
    product_description: Optional[str] = Field(None, alias="productDescription")

class ProductPlantSchema(BaseSchema):
    product: str = Field(alias="product")
    plant: str = Field(alias="plant")
    availability_check_type: Optional[str] = Field(None, alias="availabilityCheckType")
    profit_center: Optional[str] = Field(None, alias="profitCenter")
    mrp_type: Optional[str] = Field(None, alias="mrpType")

class ProductStorageLocationSchema(BaseSchema):
    product: str = Field(alias="product")
    plant: str = Field(alias="plant")
    storage_location: str = Field(alias="storageLocation")

class ProductSchema(BaseSchema):
    product: str = Field(alias="product")
    product_type: Optional[str] = Field(None, alias="productType")
    creation_date: Optional[date] = Field(None, alias="creationDate")
    created_by_user: Optional[str] = Field(None, alias="createdByUser")
    last_change_date: Optional[date] = Field(None, alias="lastChangeDate")
    last_change_datetime: Optional[datetime] = Field(None, alias="lastChangeDateTime")
    is_marked_for_deletion: bool = Field(False, alias="isMarkedForDeletion")
    product_old_id: Optional[str] = Field(None, alias="productOldId")
    gross_weight: Optional[float] = Field(None, alias="grossWeight")
    weight_unit: Optional[str] = Field(None, alias="weightUnit")
    net_weight: Optional[float] = Field(None, alias="netWeight")
    product_group: Optional[str] = Field(None, alias="productGroup")
    base_unit: Optional[str] = Field(None, alias="baseUnit")
    division: Optional[str] = Field(None, alias="division")
    industry_sector: Optional[str] = Field(None, alias="industrySector")

class SalesOrderHeaderSchema(BaseSchema):
    sales_order: str = Field(alias="salesOrder")
    sales_order_type: Optional[str] = Field(None, alias="salesOrderType")
    sales_organization: Optional[str] = Field(None, alias="salesOrganization")
    distribution_channel: Optional[str] = Field(None, alias="distributionChannel")
    organization_division: Optional[str] = Field(None, alias="organizationDivision")
    sold_to_party: Optional[str] = Field(None, alias="soldToParty")
    creation_date: Optional[date] = Field(None, alias="creationDate")
    created_by_user: Optional[str] = Field(None, alias="createdByUser")
    last_change_datetime: Optional[datetime] = Field(None, alias="lastChangeDateTime")
    total_net_amount: Optional[float] = Field(None, alias="totalNetAmount")
    overall_delivery_status: Optional[str] = Field(None, alias="overallDeliveryStatus")
    transaction_currency: Optional[str] = Field(None, alias="transactionCurrency")
    pricing_date: Optional[date] = Field(None, alias="pricingDate")
    requested_delivery_date: Optional[date] = Field(None, alias="requestedDeliveryDate")
    incoterms_classification: Optional[str] = Field(None, alias="incotermsClassification")
    incoterms_location1: Optional[str] = Field(None, alias="incotermsLocation1")
    customer_payment_terms: Optional[str] = Field(None, alias="customerPaymentTerms")

class SalesOrderItemSchema(BaseSchema):
    sales_order: str = Field(alias="salesOrder")
    sales_order_item: str = Field(alias="salesOrderItem")
    sales_order_item_category: Optional[str] = Field(None, alias="salesOrderItemCategory")
    material: Optional[str] = Field(None, alias="material")
    requested_quantity: Optional[float] = Field(None, alias="requestedQuantity")
    requested_quantity_unit: Optional[str] = Field(None, alias="requestedQuantityUnit")
    transaction_currency: Optional[str] = Field(None, alias="transactionCurrency")
    net_amount: Optional[float] = Field(None, alias="netAmount")
    material_group: Optional[str] = Field(None, alias="materialGroup")
    production_plant: Optional[str] = Field(None, alias="productionPlant")
    storage_location: Optional[str] = Field(None, alias="storageLocation")
    sales_document_rjcn_reason: Optional[str] = Field(None, alias="salesDocumentRjcnReason")

class SalesOrderScheduleLineSchema(BaseSchema):
    sales_order: str = Field(alias="salesOrder")
    sales_order_item: str = Field(alias="salesOrderItem")
    schedule_line: str = Field(alias="scheduleLine")
    confirmed_delivery_date: Optional[date] = Field(None, alias="confirmedDeliveryDate")
    order_quantity_unit: Optional[str] = Field(None, alias="orderQuantityUnit")
    confd_order_qty_by_matl_avail_check: Optional[float] = Field(None, alias="confdOrderQtyByMatlAvailCheck")
