package provider

import (
	"context"
	"fmt"
	"strings"

	"github.com/GoDeskio/Cache-Me-Outside/terraform/provider/internal/keys"
	"github.com/hashicorp/terraform-plugin-framework/resource"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/planmodifier"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/stringdefault"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/stringplanmodifier"
	"github.com/hashicorp/terraform-plugin-framework/types"
)

type apiKey struct{ admin *Admin }

type apiKeyModel struct {
	ID     types.String `tfsdk:"id"`
	Scope  types.String `tfsdk:"scope"`
	Prefix types.String `tfsdk:"prefix"`
	Secret types.String `tfsdk:"secret"`
}

func newAPIKey() resource.Resource { return &apiKey{} }

func (r *apiKey) Metadata(_ context.Context, req resource.MetadataRequest, resp *resource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_api_key"
}

func (r *apiKey) Schema(_ context.Context, _ resource.SchemaRequest, resp *resource.SchemaResponse) {
	keep := []planmodifier.String{stringplanmodifier.UseStateForUnknown()}
	resp.Schema = schema.Schema{
		Description: "A scoped API key (ACL user) on every data node. Same rules as deploy/api-key.sh.",
		Attributes: map[string]schema.Attribute{
			"id":     schema.StringAttribute{Computed: true, PlanModifiers: keep, Description: "ACL user name, key-<12hex>."},
			"scope":  schema.StringAttribute{Required: true, Description: `"ro" or "rw".`},
			"prefix": schema.StringAttribute{Optional: true, Computed: true, Default: stringdefault.StaticString(""), Description: "Key-name prefix the key may touch. Empty = all keys."},
			"secret": schema.StringAttribute{Computed: true, Sensitive: true, PlanModifiers: keep, Description: "Password. Only its SHA-256 is sent to the server; the plain value lives in Terraform state, so protect the state."},
		},
	}
}

func (r *apiKey) Configure(_ context.Context, req resource.ConfigureRequest, resp *resource.ConfigureResponse) {
	if req.ProviderData == nil {
		return
	}
	a, ok := req.ProviderData.(*Admin)
	if !ok {
		resp.Diagnostics.AddError("Bad provider data", fmt.Sprintf("%T", req.ProviderData))
		return
	}
	r.admin = a
}

func (r *apiKey) apply(m apiKeyModel) error {
	args, err := keys.SetUserArgs(m.ID.ValueString(), keys.Hash(m.Secret.ValueString()), m.Scope.ValueString(), m.Prefix.ValueString())
	if err != nil {
		return err
	}
	return r.admin.Each(args...)
}

func (r *apiKey) Create(ctx context.Context, req resource.CreateRequest, resp *resource.CreateResponse) {
	var m apiKeyModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &m)...)
	if resp.Diagnostics.HasError() {
		return
	}
	id, secret, err := keys.New()
	if err != nil {
		resp.Diagnostics.AddError("Random failed", err.Error())
		return
	}
	m.ID, m.Secret = types.StringValue(id), types.StringValue(secret)
	if err := r.apply(m); err != nil {
		_ = r.admin.Each("ACL", "DELUSER", id) // don't leave a half-made key
		resp.Diagnostics.AddError("Could not create key", err.Error())
		return
	}
	resp.Diagnostics.Append(resp.State.Set(ctx, &m)...)
}

func (r *apiKey) Read(ctx context.Context, req resource.ReadRequest, resp *resource.ReadResponse) {
	var m apiKeyModel
	resp.Diagnostics.Append(req.State.Get(ctx, &m)...)
	if resp.Diagnostics.HasError() {
		return
	}
	missing, err := r.admin.Missing(m.ID.ValueString())
	if err != nil {
		resp.Diagnostics.AddError("Could not read key", err.Error())
		return
	}
	switch {
	case len(missing) == len(r.admin.Nodes):
		resp.State.RemoveResource(ctx) // gone everywhere: plan a new key
	case len(missing) > 0:
		resp.Diagnostics.AddWarning("Key missing on some nodes",
			fmt.Sprintf("%s is missing on %s (for example after a restart). Run terraform apply -replace or change any argument to re-apply it with the same secret.", m.ID.ValueString(), strings.Join(missing, ", ")))
	}
}

func (r *apiKey) Update(ctx context.Context, req resource.UpdateRequest, resp *resource.UpdateResponse) {
	var plan, state apiKeyModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}
	plan.ID, plan.Secret = state.ID, state.Secret
	if err := r.apply(plan); err != nil {
		resp.Diagnostics.AddError("Could not update key", err.Error())
		return
	}
	resp.Diagnostics.Append(resp.State.Set(ctx, &plan)...)
}

func (r *apiKey) Delete(ctx context.Context, req resource.DeleteRequest, resp *resource.DeleteResponse) {
	var m apiKeyModel
	resp.Diagnostics.Append(req.State.Get(ctx, &m)...)
	if resp.Diagnostics.HasError() {
		return
	}
	if err := r.admin.Each("ACL", "DELUSER", m.ID.ValueString()); err != nil {
		resp.Diagnostics.AddError("Could not revoke key", err.Error())
	}
}

var _ resource.Resource = (*apiKey)(nil)
