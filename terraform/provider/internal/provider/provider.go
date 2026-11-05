package provider

import (
	"context"
	"os"
	"strings"

	"github.com/hashicorp/terraform-plugin-framework/datasource"
	"github.com/hashicorp/terraform-plugin-framework/provider"
	"github.com/hashicorp/terraform-plugin-framework/provider/schema"
	"github.com/hashicorp/terraform-plugin-framework/resource"
	"github.com/hashicorp/terraform-plugin-framework/types"
)

type cmoProvider struct{ version string }

type providerModel struct {
	Nodes    types.List   `tfsdk:"nodes"`
	TLS      types.Bool   `tfsdk:"tls"`
	Username types.String `tfsdk:"username"`
	Password types.String `tfsdk:"password"`
}

// New returns the provider factory used by main.
func New(version string) func() provider.Provider {
	return func() provider.Provider { return &cmoProvider{version: version} }
}

func (p *cmoProvider) Metadata(_ context.Context, _ provider.MetadataRequest, resp *provider.MetadataResponse) {
	resp.TypeName = "cmo"
	resp.Version = p.version
}

func (p *cmoProvider) Schema(_ context.Context, _ provider.SchemaRequest, resp *provider.SchemaResponse) {
	resp.Schema = schema.Schema{
		Description: "Manage Cache Me Outside API keys (ACL users) on every data node.",
		Attributes: map[string]schema.Attribute{
			"nodes": schema.ListAttribute{
				ElementType: types.StringType, Optional: true,
				Description: "host:port of every data node (not sentinels). Env: CMO_NODES (comma-separated).",
			},
			"tls":      schema.BoolAttribute{Optional: true, Description: "Use TLS. Env: CMO_TLS=1."},
			"username": schema.StringAttribute{Optional: true, Description: "Admin ACL user. Env: CMO_ADMIN_USER. Default: default."},
			"password": schema.StringAttribute{Optional: true, Sensitive: true, Description: "Admin password. Env: CMO_ADMIN_PASSWORD."},
		},
	}
}

// pick returns the config value, else the env var.
func pick(v types.String, env string) string {
	if !v.IsNull() && !v.IsUnknown() {
		return v.ValueString()
	}
	return os.Getenv(env)
}

func (p *cmoProvider) Configure(ctx context.Context, req provider.ConfigureRequest, resp *provider.ConfigureResponse) {
	var m providerModel
	resp.Diagnostics.Append(req.Config.Get(ctx, &m)...)
	if resp.Diagnostics.HasError() {
		return
	}
	a := &Admin{User: pick(m.Username, "CMO_ADMIN_USER"), Password: pick(m.Password, "CMO_ADMIN_PASSWORD")}
	if !m.Nodes.IsNull() && !m.Nodes.IsUnknown() {
		resp.Diagnostics.Append(m.Nodes.ElementsAs(ctx, &a.Nodes, false)...)
	} else if env := os.Getenv("CMO_NODES"); env != "" {
		for _, n := range strings.Split(env, ",") {
			if n = strings.TrimSpace(n); n != "" {
				a.Nodes = append(a.Nodes, n)
			}
		}
	}
	if !m.TLS.IsNull() {
		a.TLS = m.TLS.ValueBool()
	} else {
		a.TLS = os.Getenv("CMO_TLS") == "1"
	}
	if len(a.Nodes) == 0 {
		resp.Diagnostics.AddError("No nodes", "Set nodes or CMO_NODES to every data node's host:port.")
		return
	}
	resp.ResourceData = a
}

func (p *cmoProvider) Resources(context.Context) []func() resource.Resource {
	return []func() resource.Resource{newAPIKey}
}

func (p *cmoProvider) DataSources(context.Context) []func() datasource.DataSource { return nil }
