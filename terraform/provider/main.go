// Command terraform-provider-cmo serves the Cache Me Outside Terraform provider.
package main

import (
	"context"
	"flag"
	"log"

	"github.com/GoDeskio/Cache-Me-Outside/terraform/provider/internal/provider"
	"github.com/hashicorp/terraform-plugin-framework/providerserver"
)

var version = "dev"

func main() {
	debug := flag.Bool("debug", false, "run with debugger support")
	flag.Parse()
	err := providerserver.Serve(context.Background(), provider.New(version), providerserver.ServeOpts{
		Address: "registry.terraform.io/godeskio/cmo",
		Debug:   *debug,
	})
	if err != nil {
		log.Fatal(err)
	}
}
